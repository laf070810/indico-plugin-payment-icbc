from indico.core.plugins import IndicoPluginBlueprint

from indico_payment_icbc2.controllers import RHICBC2payNotify, RHICBC2paySuccess

blueprint = IndicoPluginBlueprint(
    "payment_icbc2",
    __name__,
    url_prefix="/event/<int:event_id>/registrations/<int:reg_form_id>/icbc2",
)

# sync return
blueprint.add_url_rule(
    "/success", "success", RHICBC2paySuccess, methods=("GET", "POST")
)

# async return
blueprint.add_url_rule("/notify", "notify", RHICBC2payNotify, methods=("POST",))
