from flask import Blueprint, render_template, session

from app.presenters.pbm_presenter import build_pbm_page_context

pbm_bp = Blueprint('pbm', __name__)

@pbm_bp.route('/pbm')
@pbm_bp.route('/pbm/overview')
def overview():
    context = build_pbm_page_context(
        pbm_name=session.get('username') or 'PBM Admin',
        pbm_id=session.get('pbm_id') or 'PBM-001',
    )
    context.setdefault('auto_approve_count', 0)
    return render_template('pages/pbm_overview.html', **context)


@pbm_bp.route('/pbm/review', strict_slashes=False)
@pbm_bp.route('/pbm/review/<path:rx_number>', strict_slashes=False)
def review(rx_number=None):
    return render_template(
        'pages/pbm_review.html',
        page_title='Final Decision | NextGen PBM',
        css_version='20260721-pbm-review-v1',
        script_version='20260721-pbm-review-v1',
        load_app_script=False,
        initial_rx_number=rx_number or '',
    )
