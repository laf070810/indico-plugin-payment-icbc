import json
from itertools import chain

import requests
from flask import flash, redirect, request
from flask_pluginengine import current_plugin
from indico.core.logger import Logger
from indico.modules.events.payment.models.transactions import TransactionAction
from indico.modules.events.payment.notifications import notify_amount_inconsistency
from indico.modules.events.payment.util import register_transaction
from indico.modules.events.registration.models.registrations import Registration
from indico.web.flask.util import url_for
from indico.web.rh import RH
from werkzeug.exceptions import BadRequest

from indico_payment_icbc import _
from indico_payment_icbc.util import RsaUtil

transaction_action_mapping = {
    "0": TransactionAction.complete,
    # "TRADE_FAIL": TransactionAction.reject,
    # "Pending": TransactionAction.pending,
}


class RHICBCpayNotify(RH):
    """Process the notification (async return) sent by the ICBCpay"""

    CSRF_ENABLED = False

    def _process_args(self):
        self.token = request.args["token"]
        self.registration = Registration.query.filter_by(uuid=self.token).first()
        if not self.registration:
            raise BadRequest
        self.biz_content = json.loads(request.form.get("biz_content"))

    def _process(self):
        # -------- verify signature --------
        # if not self._verify_signature():
        #     Logger.get().info(
        #         f"Signature verification failed. Transaction not registered. Request form: {request.form}"
        #     )
        #     return

        # -------- verify business --------
        # self._verify_business()

        # -------- verify params --------
        # verify_params = list(chain(IPN_VERIFY_EXTRA_PARAMS, request.form.items()))
        # result = requests.post(
        #     current_plugin.settings.get("url"), data=verify_params
        # ).text
        # if result != "VERIFIED":
        #     current_plugin.logger.warning(
        #         "Paypal IPN string %s did not validate (%s)", verify_params, result
        #     )
        #     return

        # -------- verify duplicated transaction --------
        if self._is_transaction_duplicated():
            current_plugin.logger.info(
                "Payment not recorded because transaction was duplicated\nData received: %s",
                request.form,
            )
            return

        # -------- verify payment status --------
        payment_status = self.biz_content["return_code"]
        if payment_status != "0":
            current_plugin.logger.info(
                "Payment failed (status: %s)\nData received: %s",
                payment_status,
                request.form,
            )
            return

        # -------- verify amount --------
        self._verify_amount()

        # -------- register transaction --------
        register_transaction(
            registration=self.registration,
            amount=float(self.biz_content["total_amt"]),
            currency=self.registration.currency,
            action=transaction_action_mapping[payment_status],
            provider="icbc",
            data=request.form,
        )

    def _verify_signature(self):
        fields_to_sign = [
            "app_id",
            "msg_id",
            "format",
            "charset",
            "encrypt_type",
            "sign_type",
            "timestamp",
            "biz_content",
        ]
        data_to_sign = {key: request.form[key] for key in fields_to_sign}

        public_key = (
            "-----BEGIN PUBLIC KEY-----"
            + """
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAzBIK71iL
hfauIPG7ebZci86gjhQ9NtzZPTmQYn0MCz905Al2XHndQOy45fkIV
A9aRo/fvDmOhYmG/9wN3hRIDTsFvRdIOKG7A7fVYF00TUZtuszDk
3MwvM2dFsf+9giQOAR2S83KeRHREyb6vIRDeGDqMX1AJfpN5rY
uzEZeqZrnig9BawFQ1pbuDtOK5u0gWz6hXZSt9vBHc7BaieDeNkh
/GxW86fvcdPmpZTvAZAqE75K7u85+KEmKnJVm2UMxrtQYqO0ut
ItUPAsesULm93Q4PPFCW9Mfex8HlvvnU13NhOW1SkKa1ktkiQQU
Tdf7Rhor80tccg5F75Guk4Yf2wIDAQAB
"""
            + "-----END PUBLIC KEY-----"
        )
        rsa_util = RsaUtil(public_key=public_key)

        encrypt_str = RsaUtil.encrypt_str(
            "/ui/cardbusiness/epaypc/consumption/V1", data_to_sign
        )
        signature = request.form["sign"]

        return rsa_util.verify_sign(encrypt_str, signature)

    def _verify_amount(self):
        expected_amount = round(self.registration.price * 100)
        expected_currency = self.registration.currency
        amount = int(self.biz_content["total_amt"])

        if expected_amount == amount:
            return True
        current_plugin.logger.warning(
            "Payment doesn't match event's fee: %s %s != %s %s",
            amount,
            "CNY",
            expected_amount,
            expected_currency,
        )
        notify_amount_inconsistency(self.registration, amount, "CNY")
        return False

    def _is_transaction_duplicated(self):
        transaction = self.registration.transaction
        if not transaction or transaction.provider != "icbc":
            return False

        # biz_content is from database. self.biz_content is from current request. We compare them
        biz_content = json.loads(transaction.data["biz_content"])
        return (
            biz_content["mer_id"] == self.biz_content["mer_id"]
            and biz_content["out_trade_no"] == self.biz_content["out_trade_no"]
        )


class RHICBCpaySuccess(RHICBCpayNotify):
    """Confirmation message after successful payment"""

    def _process(self):
        super()._process()
        flash(_("Your payment request has been processed."), "success")
        return redirect(
            url_for(
                "event_registration.display_regform",
                self.registration.locator.registrant,
            )
        )
