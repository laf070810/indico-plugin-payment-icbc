from indico.core.plugins import IndicoPluginBlueprint

from indico_payment_icbc3.controllers import RHICBC3payNotify, RHICBC3paySuccess

blueprint = IndicoPluginBlueprint(
    "payment_icbc3",
    __name__,
    url_prefix="/event/<int:event_id>/registrations/<int:reg_form_id>/icbc3",
)

# sync return
blueprint.add_url_rule(
    "/success", "success", RHICBC3paySuccess, methods=("GET", "POST")
)

# async return
blueprint.add_url_rule("/notify", "notify", RHICBC3payNotify, methods=("POST",))
