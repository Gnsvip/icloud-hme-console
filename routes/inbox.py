from flask import Blueprint

from services import mail_service

bp = Blueprint("inbox", __name__)

@bp.route('/api/accounts/<acc_id>/app-password', methods=['POST'])
def api_set_app_password(acc_id):
    return mail_service.api_set_app_password(acc_id)

@bp.route('/api/accounts/<acc_id>/inbox')
def api_inbox(acc_id):
    return mail_service.api_inbox(acc_id)

@bp.route('/api/inbox')
def api_all_inboxes():
    return mail_service.api_all_inboxes()

@bp.route('/api/inbox/search')
def api_search_inboxes():
    return mail_service.api_search_inboxes()

@bp.route('/api/accounts/<acc_id>/inbox-stream')
def api_inbox_stream(acc_id):
    return mail_service.api_inbox_stream(acc_id)

@bp.route('/api/accounts/<acc_id>/message/<msg_id>')
def api_message_body(acc_id, msg_id):
    return mail_service.api_message_body(acc_id, msg_id)

@bp.route('/api/accounts/<acc_id>/messages/prefetch', methods=['POST'])
def api_prefetch_messages(acc_id):
    return mail_service.api_prefetch_messages(acc_id)

@bp.route('/api/accounts/<acc_id>/mail/<alias_email>')
def api_specific_alias_mail(acc_id, alias_email):
    return mail_service.api_specific_alias_mail(acc_id, alias_email)

@bp.route('/api/mail')
def api_mail_by_email():
    return mail_service.api_mail_by_email()

@bp.route('/api/accounts/<acc_id>/alias-mail')
def api_alias_mail(acc_id):
    return mail_service.api_alias_mail(acc_id)
