from flask import Blueprint, render_template

review_bp = Blueprint('review', __name__)

@review_bp.route('/review')
@review_bp.route('/review/<path:rx_number>')
def review(rx_number=None):
    return render_template(
        'pages/review.html',
        page_title='Doctor Review & Final Decision | NextGen PBM',
        css_version='20260721-review-page-v6',
        script_version='20260721-review-page-v6',
        load_app_script=False,
        initial_rx_number=rx_number or '',
        provider={
            'name': 'Alex',
            'npi': '12345678',
        },
    )


@review_bp.route('/pbm/review', strict_slashes=False)
@review_bp.route('/pbm/review/<path:rx_number>', strict_slashes=False)
def pbm_review_fallback(rx_number=None):
    return render_template(
        'pages/pbm_review.html',
        page_title='Final Decision | NextGen PBM',
        css_version='20260721-pbm-review-v1',
        script_version='20260721-pbm-review-v1',
        load_app_script=False,
        initial_rx_number=rx_number or '',
    )
