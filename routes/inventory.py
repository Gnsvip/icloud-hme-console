from flask import Blueprint

from services import code_inventory_service

bp = Blueprint("inventory", __name__)

@bp.route('/api/aliases')
def api_aliases():
    return code_inventory_service.api_aliases()

@bp.route('/api/aliases/cache')
def api_aliases_cache():
    return code_inventory_service.api_aliases_cache()

@bp.route('/api/emails')
def api_emails():
    return code_inventory_service.api_emails()

@bp.route('/api/inventory')
def api_inventory():
    return code_inventory_service.api_inventory()

@bp.route('/api/inventory/sync', methods=['POST'])
def api_inventory_sync():
    return code_inventory_service.api_inventory_sync()

@bp.route('/api/inventory/<path:email_addr>/move', methods=['POST'])
def api_inventory_move(email_addr):
    return code_inventory_service.api_inventory_move(email_addr)

@bp.route('/api/inventory/<path:email_addr>/remark', methods=['POST'])
def api_inventory_remark(email_addr):
    return code_inventory_service.api_inventory_remark(email_addr)

@bp.route('/api/inventory/<path:email_addr>/mark-read', methods=['POST'])
def api_inventory_mark_read(email_addr):
    return code_inventory_service.api_inventory_mark_read(email_addr)

@bp.route('/api/inventory/<path:email_addr>/trash', methods=['POST'])
def api_inventory_trash(email_addr):
    return code_inventory_service.api_inventory_trash(email_addr)

@bp.route('/api/inventory/<path:email_addr>/purge', methods=['POST'])
def api_inventory_purge(email_addr):
    return code_inventory_service.api_inventory_purge(email_addr)

@bp.route('/api/inventory/export')
def api_inventory_export():
    return code_inventory_service.api_inventory_export()

@bp.route('/api/inventory/check-icloud', methods=['POST'])
def api_inventory_check_icloud():
    return code_inventory_service.api_inventory_check_icloud()

@bp.route('/api/inventory/calibrate-cloud', methods=['POST'])
def api_inventory_calibrate_cloud():
    return code_inventory_service.api_inventory_calibrate_cloud()

@bp.route('/api/inventory/check-forward', methods=['POST'])
def api_inventory_check_forward():
    return code_inventory_service.api_inventory_check_forward()

@bp.route('/api/forward-config', methods=['GET', 'POST'])
def api_forward_config():
    return code_inventory_service.api_forward_config()

@bp.route('/api/forward-config/<profile_id>', methods=['DELETE'])
def api_forward_config_delete(profile_id):
    return code_inventory_service.api_forward_config_delete(profile_id)

@bp.route('/api/forward-config/<profile_id>/microsoft/start', methods=['POST'])
def api_forward_microsoft_start(profile_id):
    return code_inventory_service.api_forward_microsoft_start(profile_id)

@bp.route('/api/forward-config/<profile_id>/microsoft/poll', methods=['POST'])
def api_forward_microsoft_poll(profile_id):
    return code_inventory_service.api_forward_microsoft_poll(profile_id)
