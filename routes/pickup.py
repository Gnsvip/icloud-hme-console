from flask import Blueprint, render_template, request

from services import mail_service

bp = Blueprint("pickup", __name__)


@bp.route("/c/<link_id>")
def page_pickup_link(link_id):
    record = mail_service.resolve_pickup_link(link_id, request.args.get("token", ""))
    if not record:
        return render_template(
            "pickup.html",
            pickup_locked=True,
            pickup_access_denied=True,
            pickup_link_id=link_id,
        ), 403
    return render_template(
        "pickup.html",
        pickup_email=record["email"],
        pickup_locked=True,
        pickup_link_id=record["id"],
    )


@bp.route("/api/public/latest-code/<mailbox_id>")
def api_public_latest_code(mailbox_id):
    return mail_service.api_public_latest_code(
        mailbox_id,
        request.args.get("token", ""),
    )


@bp.route("/api/pickup-links/for-email/<path:email_addr>", methods=["POST"])
def api_pickup_link_for_email(email_addr):
    return mail_service.api_pickup_link_for_email(email_addr)


@bp.route("/api/pickup-links/batch", methods=["POST"])
def api_pickup_links_batch():
    return mail_service.api_pickup_links_batch()


@bp.route("/api/pickup-links")
def api_pickup_links():
    return mail_service.api_pickup_links()


@bp.route("/api/pickup-links/<link_id>", methods=["DELETE"])
def api_revoke_pickup_link(link_id):
    return mail_service.api_revoke_pickup_link(link_id)


@bp.route("/api/pickup-links/revoke-batch", methods=["POST"])
def api_revoke_pickup_links_batch():
    return mail_service.api_revoke_pickup_links_batch()
