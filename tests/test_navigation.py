from test_activities import _login

NAV_LINK_CLASS = "govuk-service-navigation__link"


def test_add_page_permitted_for_contributor(activities_client, activities_web_engine):
    _login(activities_client, activities_web_engine, "Cody Contributor")
    response = activities_client.get("/add")
    assert response.status_code == 200
    assert 'href="/intake/new"' in response.text
    assert 'href="/intake/assets/new"' in response.text
    assert 'href="/intake"' in response.text


def test_add_page_forbidden_for_viewer(activities_client, activities_web_engine):
    _login(activities_client, activities_web_engine, "Vic Viewer")
    response = activities_client.get("/add")
    assert response.status_code == 403


def test_add_page_shows_import_link_for_curator_not_contributor(
    activities_client, activities_web_engine
):
    _login(activities_client, activities_web_engine, "Cara Curator")
    curator_page = activities_client.get("/add")
    assert curator_page.status_code == 200
    assert 'href="/imports"' in curator_page.text

    _login(activities_client, activities_web_engine, "Cody Contributor")
    contributor_page = activities_client.get("/add")
    assert contributor_page.status_code == 200
    assert 'href="/imports"' not in contributor_page.text


def test_add_page_wording_distinguishes_all_vs_my_submissions(
    activities_client, activities_web_engine
):
    _login(activities_client, activities_web_engine, "Cara Curator")
    curator_page = activities_client.get("/add")
    assert "All submissions" in curator_page.text
    assert "My submissions" not in curator_page.text

    _login(activities_client, activities_web_engine, "Cody Contributor")
    contributor_page = activities_client.get("/add")
    assert "My submissions" in contributor_page.text
    assert "All submissions" not in contributor_page.text


def test_review_page_permitted_for_curator(activities_client, activities_web_engine):
    _login(activities_client, activities_web_engine, "Cara Curator")
    response = activities_client.get("/review")
    assert response.status_code == 200
    assert 'href="/intake/gaps"' in response.text
    assert 'href="/vocabularies"' in response.text
    assert 'href="/assets"' in response.text
    assert 'href="/complaints"' in response.text


def test_review_page_forbidden_for_contributor(activities_client, activities_web_engine):
    _login(activities_client, activities_web_engine, "Cody Contributor")
    response = activities_client.get("/review")
    assert response.status_code == 403


def test_manage_page_permitted_for_approver_dpo(activities_client, activities_web_engine):
    _login(activities_client, activities_web_engine, "Ada Approver")
    response = activities_client.get("/manage")
    assert response.status_code == 200
    assert 'href="/users"' in response.text
    assert 'href="/regime-policy"' in response.text
    assert 'href="/vocabularies"' in response.text


def test_manage_page_forbidden_for_curator(activities_client, activities_web_engine):
    _login(activities_client, activities_web_engine, "Cara Curator")
    response = activities_client.get("/manage")
    assert response.status_code == 403


def test_register_page_has_sibling_register_links(activities_client, activities_web_engine):
    _login(activities_client, activities_web_engine, "Vic Viewer")
    response = activities_client.get("/register")
    assert response.status_code == 200
    assert 'href="/activities"' in response.text
    assert 'href="/assets"' in response.text
    assert 'href="/register/export/art30_1"' in response.text
    assert 'href="/register/export/art30_2"' in response.text
    assert 'href="/assets/export.csv"' in response.text


def test_nav_does_not_duplicate_the_asset_intake_wizard(
    activities_client, activities_web_engine
):
    """The wizard belongs under Add information, not as its own nav entry. It may
    still appear in page content as a call to action — the duplication that
    confused people was in the menu itself."""
    _login(activities_client, activities_web_engine, "Cody Contributor")
    response = activities_client.get("/")
    assert response.status_code == 200
    nav = response.text[
        response.text.index("govuk-service-navigation") : response.text.index("</nav>")
    ]
    assert "/intake/assets/new" not in nav
    assert "/intake" not in nav


def test_nav_renders_on_non_dashboard_page(seeded_client, seeded_web_engine):
    _login(seeded_client, seeded_web_engine, "Ada Approver")
    response = seeded_client.get("/activities")
    assert response.status_code == 200
    assert "govuk-service-navigation" in response.text
    assert NAV_LINK_CLASS in response.text


def test_nav_absent_on_login_page(seeded_client):
    response = seeded_client.get("/login")
    assert response.status_code == 200
    assert "govuk-service-navigation" not in response.text


def test_nav_active_item_marked(seeded_client, seeded_web_engine):
    _login(seeded_client, seeded_web_engine, "Ada Approver")
    response = seeded_client.get("/register")
    assert response.status_code == 200
    assert 'aria-current="true"' in response.text
