from indico.core.plugins import IndicoPluginBlueprint

from indico_payment_icbc.controllers import RHICBCpayNotify, RHICBCpaySuccess

blueprint = IndicoPluginBlueprint(
    "payment_icbc",
    __name__,
    url_prefix="/event/<int:event_id>/registrations/<int:reg_form_id>/icbc",
)

# sync return
blueprint.add_url_rule("/success", "success", RHICBCpaySuccess, methods=("GET", "POST"))

# async return
blueprint.add_url_rule("/notify", "notify", RHICBCpayNotify, methods=("POST",))
