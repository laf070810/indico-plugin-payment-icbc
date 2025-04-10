import json
import time
from urllib.parse import urlparse

from flask_pluginengine import current_plugin, render_plugin_template
from indico.core.logger import Logger
from indico.core.plugins import IndicoPlugin, url_for_plugin
from indico.modules.events.payment import (
    PaymentEventSettingsFormBase,
    PaymentPluginMixin,
    PaymentPluginSettingsFormBase,
)
from indico.modules.events.payment.models.transactions import TransactionAction
from indico.modules.events.payment.util import register_transaction
from indico.modules.events.registration.models.registrations import (
    Registration,
    RegistrationState,
)
from indico.util.string import remove_accents, str_to_ascii
from indico.web.forms.validators import UsedIf
from sqlalchemy.orm.exc import MultipleResultsFound, NoResultFound
from wtforms.fields import IntegerField, StringField, URLField
from wtforms.validators import DataRequired, Optional, Regexp

from indico_payment_icbc2 import _
from indico_payment_icbc2.blueprint import blueprint
from indico_payment_icbc2.util import RsaUtil, aes_encrypt


class PluginSettingsForm(PaymentPluginSettingsFormBase):
    url = URLField(
        _("API URL"), [DataRequired()], description=_("URL of the ICBCpay HTTP API.")
    )
    url_foreign = URLField(
        _("API URL of foreign pay"),
        [DataRequired()],
        description=_("URL of the ICBC foreign pay HTTP API."),
    )
    app_id = StringField(
        _("app_id"),
        [Optional()],
        description=_(
            "The project number. Event managers will be able to override this."
        ),
    )
    mer_id = StringField(
        _("mer_id"),
        [Optional()],
        description=_("The merchant ID. Event managers will be able to override this."),
    )
    mer_prtcl_no = StringField(
        _("mer_prtcl_no"),
        [Optional()],
        description=_(
            "The merchant protocol number. Event managers will be able to override this."
        ),
    )
    sign_key = StringField(
        _("sign_key"),
        [Optional()],
        description=_(
            "The private key of the project. Event managers will be able to override this."
        ),
    )
    encrypt_key = StringField(
        _("encrypt_key"),
        [Optional()],
        description=_(
            "The key for symmetric encryption of the project. Event managers will be able to override this."
        ),
    )


class EventSettingsForm(PaymentEventSettingsFormBase):
    app_id = StringField(
        _("app_id"),
        [UsedIf(lambda form, _: form.enabled.data), DataRequired()],
        description=_("The project number."),
    )
    sign_key = StringField(
        _("sign_key"),
        [UsedIf(lambda form, _: form.enabled.data), DataRequired()],
        description=_("The private key of the project."),
    )
    encrypt_key = StringField(
        _("encrypt_key"),
        [UsedIf(lambda form, _: form.enabled.data), DataRequired()],
        description=_("The key for symmetric encryption of the project."),
    )
    mer_id = StringField(
        _("mer_id"),
        [UsedIf(lambda form, _: form.enabled.data), DataRequired()],
        description=_("The merchant ID."),
    )
    mer_prtcl_no = StringField(
        _("mer_prtcl_no"),
        [UsedIf(lambda form, _: form.enabled.data), DataRequired()],
        description=_("The merchant protocol number."),
    )
    allowed_registration_form_ids = StringField(
        _("allowed_registration_form_ids"),
        [
            UsedIf(lambda form, _: form.enabled.data),
            Regexp(r"\[\d+( *, *\d+)*\]"),
            Optional(),
        ],
        description=_(
            "(whitelist) JSON string of non-empty list of IDs of the registration forms which are allowed to use this payment method. Registration forms that are not in this list are not allowed. Empty string for no requirement. Actual allowed registration forms are the intersection of the allowed ones of allowed_registration_form_ids and disallowed_registration_form_ids."
        ),
    )
    disallowed_registration_form_ids = StringField(
        _("disallowed_registration_form_ids"),
        [
            UsedIf(lambda form, _: form.enabled.data),
            Regexp(r"\[\d+( *, *\d+)*\]"),
            Optional(),
        ],
        description=_(
            "(blacklist) JSON string of non-empty list of IDs of the registration forms which are not allowed to use this payment method. Registration forms that are not in this list are allowed. Empty string for no requirement. Actual allowed registration forms are the intersection of the allowed ones of allowed_registration_form_ids and disallowed_registration_form_ids."
        ),
    )
    completed_registration_form_id = IntegerField(
        _("completed_registration_form_id"),
        [UsedIf(lambda form, _: form.enabled.data), Optional()],
        description=_(
            "ID of the registration form which is required to be completed before the payment. Empty for no requirement. Currently only one completed registration form is supported."
        ),
    )
    uncompleted_registration_form_id = IntegerField(
        _("uncompleted_registration_form_id"),
        [UsedIf(lambda form, _: form.enabled.data), Optional()],
        description=_(
            "ID of the registration form which is required to be uncompleted before the payment. Empty for no requirement. Currently only one uncompleted registration form is supported."
        ),
    )
    custom_payment_name = StringField(
        _("custom_payment_name"),
        [UsedIf(lambda form, _: form.enabled.data), Optional()],
        description=_(
            "Custom payment name. Used in tradeName and tradeSummary. If empty, the title of the event will be used. "
        ),
    )


class ICBC2PaymentPlugin(PaymentPluginMixin, IndicoPlugin):
    """ICBCpay

    Plugin for integrating ICBCpay as a payment method in Indico.
    """

    configurable = True
    settings_form = PluginSettingsForm
    event_settings_form = EventSettingsForm
    default_settings = {
        "method_name": "ICBC2",
        "url": "https://gw.open.icbc.com.cn/ui/cardbusiness/epaypc/consumption/V1",
        "url_foreign": "https://gw.open.icbc.com.cn/ui/cardbusiness/aggregatepay/b2c/online/ui/foreignpay/V1",
        "app_id": "",
        "sign_key": "",
        "encrypt_key": "",
        "mer_id": "",
        "mer_prtcl_no": "",
    }
    default_event_settings = {
        "enabled": False,
        "method_name": None,
        "app_id": None,
        "sign_key": None,
        "encrypt_key": None,
        "mer_id": None,
        "mer_prtcl_no": None,
        "allowed_registration_form_ids": "",
        "disallowed_registration_form_ids": "",
        "completed_registration_form_id": None,
        "uncompleted_registration_form_id": None,
        "custom_payment_name": "",
    }

    def init(self):
        super().init()

    @property
    def logo_url(self):
        return url_for_plugin(self.name + ".static", filename="images/logo.png")

    def get_blueprints(self):
        return blueprint

    def adjust_payment_form_data(self, data):
        settings = data["settings"]
        event_settings = data["event_settings"]
        event = data["event"]
        registration = data["registration"]
        plain_name = remove_accents(registration.full_name)
        plain_title = remove_accents(
            event.title
            if event_settings["custom_payment_name"] == ""
            else event_settings["custom_payment_name"]
        )
        amount = data["amount"]
        currency = data["currency"]

        # -------- deal with allowed_registration_form_ids and disallowed_registration_form_ids --------
        allowed_registration_form_ids = (
            json.loads(event_settings["allowed_registration_form_ids"])
            if event_settings["allowed_registration_form_ids"] != ""
            else None
        )
        disallowed_registration_form_ids = (
            json.loads(event_settings["disallowed_registration_form_ids"])
            if event_settings["disallowed_registration_form_ids"] != ""
            else []
        )

        if allowed_registration_form_ids is not None:
            if registration.registration_form_id not in allowed_registration_form_ids:
                data["payment_allowed"] = False
                data["message"] = (
                    "Payment method not allowed in this registration form! Please use appropriate methods. "
                )
                return
            elif registration.registration_form_id in disallowed_registration_form_ids:
                data["payment_allowed"] = False
                data["message"] = (
                    "Payment method not allowed in this registration form! Please use appropriate methods. "
                )
                return
            else:
                data["payment_allowed"] = True
        elif registration.registration_form_id in disallowed_registration_form_ids:
            data["payment_allowed"] = False
            data["message"] = (
                "Payment method not allowed in this registration form! Please use appropriate methods. "
            )
            return
        else:
            data["payment_allowed"] = True

        # -------- deal with completed_registration_form_id --------
        completed_registration_form_id = event_settings[
            "completed_registration_form_id"
        ]

        if (completed_registration_form_id is not None) and (
            completed_registration_form_id != registration.registration_form_id
        ):
            try:
                related_registration = Registration.query.filter(
                    Registration.is_active,
                    # Registration.first_name == registration.first_name,
                    # Registration.last_name == registration.last_name,
                    Registration.email == registration.email,
                    Registration.registration_form_id == completed_registration_form_id,
                ).one()
            except NoResultFound:
                data["payment_allowed"] = False
                data["message"] = (
                    "No related registration found! Please refer to the notices and complete the related registration first. "
                )
                return
            except MultipleResultsFound:
                data["payment_allowed"] = False
                data["message"] = (
                    "Multiple registrations with the same email in the related registration found! Please contact the organizers to resolve the conflict. "
                )
                return
            else:
                if related_registration.state != RegistrationState.complete:
                    data["payment_allowed"] = False
                    data["message"] = (
                        "Related registration has not been completed. Please refer to the notices and complete the related registration first."
                    )
                    return
                else:
                    data["payment_allowed"] = True
        else:
            data["payment_allowed"] = True

        # -------- deal with uncompleted_registration_form_id --------
        uncompleted_registration_form_id = event_settings[
            "uncompleted_registration_form_id"
        ]

        if (uncompleted_registration_form_id is not None) and (
            uncompleted_registration_form_id != registration.registration_form_id
        ):
            try:
                related_registration = Registration.query.filter(
                    Registration.is_active,
                    # Registration.first_name == registration.first_name,
                    # Registration.last_name == registration.last_name,
                    Registration.email == registration.email,
                    Registration.registration_form_id
                    == uncompleted_registration_form_id,
                ).one()
            except NoResultFound:
                data["payment_allowed"] = True
            except MultipleResultsFound:
                data["payment_allowed"] = False
                data["message"] = (
                    "Multiple registrations with the same email in the related registration found! Please contact the organizers to resolve the conflict. "
                )
                return
            else:
                if related_registration.state == RegistrationState.complete:
                    data["payment_allowed"] = False
                    data["message"] = (
                        "Related registration has been completed. This payment is not allowed. Please refer to the notices."
                    )
                    return
                else:
                    data["payment_allowed"] = True
        else:
            data["payment_allowed"] = True

        # -------- now the payment method is allowed --------

        # -------- pay logo url --------
        data["logo_url"] = url_for_plugin(
            self.name + ".static", filename="images/logo.png"
        )

        # -------- get current time --------
        current_time = time.time()

        # -------- common fields --------
        data["app_id"] = event_settings["app_id"]
        data["msg_id"] = str(current_time)
        data["format"] = "json"
        data["charset"] = "UTF-8"
        data["encrypt_type"] = "AES"
        data["sign_type"] = "RSA2"
        data["timestamp"] = time.strftime(
            "%Y-%m-%d %H:%M:%S", time.localtime(current_time)
        )

        # -------- biz content --------
        goods_name = f"{registration.registration_form.title} of {plain_title}"
        goods_name = goods_name[:20]

        trade_summary = f"{plain_name} ({registration.email}) payment for {registration.registration_form.title} of {plain_title}"
        trade_summary = trade_summary[:150]

        biz_content = {}
        biz_content["icbc_flag"] = "1"
        biz_content["icbc_appid"] = event_settings["app_id"]
        biz_content["order_date"] = time.strftime(
            "%Y%m%d%H%M%S", time.localtime(current_time)
        )
        biz_content["out_trade_no"] = str(current_time)
        biz_content["amount"] = str(round(amount * 100))
        biz_content["installment_times"] = "1"
        biz_content["cur_type"] = "001"
        biz_content["mer_id"] = event_settings["mer_id"]
        biz_content["mer_prtcl_no"] = event_settings["mer_prtcl_no"]
        biz_content["goods_id"] = str(registration.friendly_id)
        biz_content["goods_name"] = goods_name
        biz_content["mer_reference"] = urlparse(
            url_for_plugin(
                "payment_icbc2.notify", registration.locator.uuid, _external=True
            )
        ).hostname
        biz_content["mer_url"] = url_for_plugin(
            "payment_icbc2.success", registration.locator.uuid, _external=True
        )
        biz_content["return_url"] = url_for_plugin(
            "payment_icbc2.success", registration.locator.uuid, _external=True
        )
        biz_content["credit_type"] = "2"
        biz_content["expire_time"] = time.strftime(
            "%Y%m%d%H%M%S", time.localtime(current_time + 900)
        )
        biz_content["verify_join_flag"] = "0"
        biz_content["mer_custom_id"] = registration.email
        biz_content["mer_order_remark"] = trade_summary
        biz_content["page_linkage_flag"] = "1"

        data["biz_content"] = aes_encrypt(
            json.dumps(biz_content, separators=(",", ":")),
            event_settings["encrypt_key"],
        )
        # data["biz_content"] = json.dumps(biz_content, separators=(",", ":"))

        # -------- biz content: foreign --------
        biz_content_foreign = {}
        biz_content_foreign["client_type"] = "0"
        biz_content_foreign["icbc_appid"] = event_settings["app_id"]
        biz_content_foreign["out_trade_no"] = str(current_time)
        biz_content_foreign["amount"] = str(round(amount * 100))
        biz_content_foreign["installment_times"] = "1"
        biz_content_foreign["cur_type"] = "001"
        biz_content_foreign["mer_id"] = event_settings["mer_id"]
        biz_content_foreign["mer_prtcl_no"] = event_settings["mer_prtcl_no"]
        biz_content_foreign["mer_url"] = url_for_plugin(
            "payment_icbc2.success", registration.locator.uuid, _external=True
        )
        biz_content_foreign["return_url"] = url_for_plugin(
            "payment_icbc2.success", registration.locator.uuid, _external=True
        )
        biz_content_foreign["attach"] = registration.email
        biz_content_foreign["is_applepay"] = "0"
        biz_content_foreign["order_apd_inf"] = trade_summary[:70]

        data["biz_content_foreign"] = aes_encrypt(
            json.dumps(biz_content_foreign, separators=(",", ":")),
            event_settings["encrypt_key"],
        )

        # -------- signing --------
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
        data_to_sign = {key: data[key] for key in fields_to_sign}

        private_key = (
            "-----BEGIN RSA PRIVATE KEY-----\n"
            + event_settings["sign_key"]
            + "\n-----END RSA PRIVATE KEY-----"
        )
        rsa_util = RsaUtil(private_key=private_key)

        encrypt_str = RsaUtil.encrypt_str(urlparse(settings["url"]).path, data_to_sign)
        signature = rsa_util.create_sign(encrypt_str)
        data["sign"] = signature

        # -------- signing: foreign --------
        fields_to_sign = [
            "app_id",
            "msg_id",
            "format",
            "charset",
            "encrypt_type",
            "sign_type",
            "timestamp",
            "biz_content_foreign",
        ]
        data_to_sign = {
            key.replace("biz_content_foreign", "biz_content"): data[key]
            for key in fields_to_sign
        }

        encrypt_str = RsaUtil.encrypt_str(
            urlparse(settings["url_foreign"]).path, data_to_sign
        )
        signature = rsa_util.create_sign(encrypt_str)
        data["sign_foreign"] = signature

        # -------- register unfinished transaction for later querying --------
        register_transaction(
            registration=registration,
            amount=amount,
            currency=registration.currency,
            action=TransactionAction.pending,
            provider="icbc2",
            data=None,
        )
        register_transaction(
            registration=registration,
            amount=amount,
            currency=registration.currency,
            action=TransactionAction.reject,
            provider="icbc2",
            data={"biz_content": json.dumps(biz_content)},
        )

        # -------- get URL --------
        # fields_to_pass_by_url = [
        #     "app_id",
        #     "msg_id",
        #     "format",
        #     "charset",
        #     "encrypt_type",
        #     "sign_type",
        #     "sign",
        #     "timestamp",
        # ]
        # data_to_pass_by_url = {key: data[key] for key in fields_to_pass_by_url}
        # data["url"] = f"{settings['url']}?{urllib.parse.urlencode(data_to_pass_by_url)}"

        # # -------- dealing with foreign card parameters --------
        # data["method_fc"] = "trade.pay.page.fc"

        # biz_content["paymentChannel"] = "boc.page.fc"
        # data["bizContent_fc"] = json.dumps(biz_content)

        # data_to_sign["method"] = data["method_fc"]
        # data_to_sign["bizContent"] = data["bizContent_fc"]
        # encrypt_str = rsa_util.encrypt_str(data_to_sign)
        # signature = rsa_util.create_sign(encrypt_str)
        # data["sign_fc"] = signature

        current_plugin.logger.info(f"payment form biz_content: {biz_content}")
        current_plugin.logger.info(
            f"payment form biz_content_foreign: {biz_content_foreign}"
        )
        current_plugin.logger.info(f"payment form encrypt_str: {encrypt_str}")
