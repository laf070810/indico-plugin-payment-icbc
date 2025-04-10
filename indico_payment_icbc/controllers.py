import json
import time
from itertools import chain
from urllib.parse import urlparse

import requests
from flask import flash, redirect, request
from flask_pluginengine import current_plugin
from indico.core.logger import Logger
from indico.modules.events.payment.models.transactions import (
    TransactionAction,
    TransactionStatus,
)
from indico.modules.events.payment.notifications import notify_amount_inconsistency
from indico.modules.events.payment.util import register_transaction
from indico.modules.events.registration.models.registrations import Registration
from indico.web.flask.util import url_for
from indico.web.rh import RH
from werkzeug.exceptions import BadRequest

from indico_payment_icbc import _
from indico_payment_icbc.util import RsaUtil, aes_decrypt, aes_encrypt

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
        self.event = self.registration.event

        self._get_response_form()
        self.biz_content = json.loads(self.response_form["biz_content"])

        Logger.get().info(request)
        Logger.get().info(self.response_form)

    def _get_response_form(self):
        self.response_form = request.form

    def _process(self):
        # -------- verify signature --------
        if not self._verify_signature():
            # Logger.get().info(
            #     f"Signature verification failed. Request form: {self.response_form}"
            # )
            Logger.get().info(
                f"Signature verification failed. Transaction not registered. Request form: {self.response_form}"
            )
            return
        else:
            Logger.get().info(f"Signature verification succeeded.")

        # -------- verify business --------
        # self._verify_business()

        # -------- verify params --------
        # verify_params = list(chain(IPN_VERIFY_EXTRA_PARAMS, self.response_form.items()))
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
                self.response_form,
            )
            return

        # -------- verify payment status --------
        payment_status = self.biz_content.get(
            "pay_status", self.biz_content["return_code"]
        )
        if payment_status != "0":
            current_plugin.logger.info(
                "Payment failed (status: %s)\nData received: %s",
                payment_status,
                self.response_form,
            )
            return

        # -------- verify amount --------
        self._verify_amount()

        # -------- register transaction --------
        register_transaction(
            registration=self.registration,
            amount=float(self.biz_content["total_amt"]) / 100,
            currency=self.registration.currency,
            action=transaction_action_mapping[payment_status],
            provider="icbc",
            data=self.response_form,
        )

    def _verify_signature(self):
        fields_to_sign = [key for key in self.response_form.keys() if key != "sign"]
        data_to_sign = {key: self.response_form[key] for key in fields_to_sign}

        rsa_util = RsaUtil(public_key=RsaUtil.ICBC_PUBLIC_KEY)

        encrypt_str = RsaUtil.encrypt_str("/notifyUrlServlet", data_to_sign)
        signature = self.response_form["sign"]

        current_plugin.logger.info(encrypt_str)
        current_plugin.logger.info(signature)

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
        if (
            not transaction
            or transaction.provider != "icbc"
            or transaction.status != TransactionStatus.successful
        ):
            return False

        # biz_content is from database. self.biz_content is from current request. We compare them
        biz_content = json.loads(transaction.data["biz_content"])
        return (
            biz_content["mer_id"] == self.biz_content["mer_id"]
            and biz_content["out_trade_no"] == self.biz_content["out_trade_no"]
        )


class RHICBCpaySuccess(RHICBCpayNotify):
    """Confirmation message after successful payment"""

    def _get_response_form(self):
        self.response_form = self._query_result()

    def _process(self):
        super()._process()

        flash(_("Your payment request has been processed."), "success")
        return redirect(
            url_for(
                "event_registration.display_regform",
                self.registration.locator.registrant,
            )
        )

    def _query_result(self):
        url = "https://gw.open.icbc.com.cn/api/cardbusiness/aggregatepay/b2c/online/orderqry/V1"
        event_settings = current_plugin.event_settings.get_all(self.event)

        # -------- get current time --------
        current_time = time.time()

        # -------- common fields --------
        data = {}
        data["app_id"] = event_settings["app_id"]
        data["msg_id"] = str(current_time)
        data["charset"] = "UTF-8"
        data["encrypt_type"] = "AES"
        data["sign_type"] = "RSA2"
        data["timestamp"] = time.strftime(
            "%Y-%m-%d %H:%M:%S", time.localtime(current_time)
        )

        # -------- biz content --------
        biz_content = {}
        biz_content["mer_id"] = event_settings["mer_id"]
        biz_content["out_trade_no"] = json.loads(
            self.registration.transaction.data["biz_content"]
        )["out_trade_no"]
        biz_content["deal_flag"] = "0"
        biz_content["icbc_app_id"] = event_settings["app_id"]
        biz_content["mer_prtcl_no"] = event_settings["mer_prtcl_no"]

        data["biz_content"] = aes_encrypt(
            json.dumps(biz_content, separators=(",", ":")),
            event_settings["encrypt_key"],
        )

        # -------- signing --------
        fields_to_sign = [key for key in data.keys() if key != "sign"]
        data_to_sign = {key: data[key] for key in fields_to_sign}

        private_key = (
            "-----BEGIN RSA PRIVATE KEY-----\n"
            + event_settings["sign_key"]
            + "\n-----END RSA PRIVATE KEY-----"
        )
        rsa_util = RsaUtil(private_key=private_key)

        encrypt_str = RsaUtil.encrypt_str(urlparse(url).path, data_to_sign)
        signature = rsa_util.create_sign(encrypt_str)
        data["sign"] = signature

        # -------- request and get response --------
        response = requests.post(url, data=data)
        response.encoding = "uft-8"

        response_json = response.json()
        response_biz_content = response_json["response_biz_content"]
        response_biz_content_decrypted = aes_decrypt(
            response_biz_content, event_settings["encrypt_key"]
        )
        response_json["biz_content"] = response_biz_content_decrypted

        return response_json

    def _verify_signature(self):
        rsa_util = RsaUtil(public_key=RsaUtil.ICBC_PUBLIC_KEY)

        encrypt_str = self.response_form["response_biz_content"]
        signature = self.response_form["sign"]

        verification_result = rsa_util.verify_sign(f'"{encrypt_str}"', signature)

        return verification_result
