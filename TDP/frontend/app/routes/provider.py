from flask import Blueprint, render_template, session

from app.presenters.provider_presenter import build_provider_page_context

provider_bp = Blueprint('provider', __name__)

@provider_bp.route('/provider')
@provider_bp.route('/provider/overview')
def overview():
    return render_template(
        'pages/provider_overview.html',
        **build_provider_page_context(
            provider_name=session.get('username') or 'Provider',
            provider_npi=session.get('provider_npi'),
        )
    )
