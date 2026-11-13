"""Regression tests ensuring SaaS /bot/api/* proxy & /api/* never return HTML for JSON callers."""
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

_DB_FILE = REPO / "database.json"


@pytest.fixture(scope="module")
def saas_client():
    backup = _DB_FILE.read_text(encoding="utf-8") if _DB_FILE.exists() else None
    if _DB_FILE.exists():
        _DB_FILE.unlink()
    os.environ.setdefault("ADMIN_SECRET", "test-admin-secret-pytest")
    os.chdir(REPO)
    # Other test modules may prepend bot-engine/ to sys.path during collection;
    # keep repo root at index 0 so `import app` resolves to SaaS app.py.
    sys.path.insert(0, str(REPO))
    import app as saas
    import mobile_api

    saas.app.config["TESTING"] = True
    permissive = lambda *a, **k: True
    saas._check_rate_limit = permissive
    mobile_api._cfg["rate_limit"] = permissive
    with saas.app.test_client() as c:
        yield c, saas
    if backup is not None:
        _DB_FILE.write_text(backup, encoding="utf-8")
    elif _DB_FILE.exists():
        _DB_FILE.unlink()


class TestProxyJsonErrors:
    @pytest.mark.parametrize(
        "method,path",
        [
            ("POST", "/bot/api/config"),
            ("POST", "/bot/api/start"),
            ("GET", "/bot/api/config"),
            ("GET", "/bot/socket.io/?EIO=4&transport=polling"),
        ],
    )
    def test_unauthenticated_proxy_api_returns_401_json_not_redirect(self, saas_client, method, path):
        """Expired/logged-out /bot/api/* calls must get 401 JSON instead of 302 -> HTML '/'."""
        _, saas = saas_client
        with saas.app.test_client() as fresh:
            resp = fresh.open(path, method=method, json={} if method == "POST" else None)
        assert resp.status_code == 401
        assert resp.is_json
        body = resp.get_json()
        assert body["success"] is False
        assert body["auth_expired"] is True

    def test_unauthenticated_bot_page_still_redirects_to_home(self, saas_client):
        _, saas = saas_client
        with saas.app.test_client() as fresh:
            resp = fresh.get("/bot/")
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/")

    def test_unknown_api_endpoint_returns_json_404(self, saas_client):
        c, _ = saas_client
        resp = c.get("/api/nonexistent_route_check")
        assert resp.status_code == 404
        assert resp.is_json
        assert resp.get_json()["success"] is False

    def test_proxy_upstream_exception_returns_json_502_for_api(self, saas_client):
        c, saas = saas_client
        uid = "proxy-err-user"
        saas.DB.setdefault("users", {})[uid] = {
            "id": uid,
            "email": "proxyerr@test.com",
            "role": "user",
            "banned": False,
            "subscription": {"expires_at": "2099-01-01T00:00:00Z", "plan": "monthly"},
        }
        with c.session_transaction() as sess:
            sess["user_id"] = uid
            sess["email"] = "proxyerr@test.com"

        with patch.object(saas, "get_bot_status", return_value={"running": True, "port": 5999}), \
             patch.object(saas.req_lib, "request", side_effect=RuntimeError("boom")):
            resp = c.post("/bot/api/start", json={})

        assert resp.status_code == 502
        assert resp.is_json
        body = resp.get_json()
        assert body["success"] is False
        assert "Proxy error" in body["error"]

    def test_frontend_parse_api_json_handles_html_without_syntax_error(self):
        """parseApiJson in bot-engine/static/js/app.js must reject HTML cleanly without SyntaxError."""
        script = r"""
const fs = require('fs');
const vm = require('vm');
const src = fs.readFileSync('bot-engine/static/js/app.js', 'utf8');
const match = src.match(/async function parseApiJson[\s\S]*?\n\}/);
if (!match) throw new Error('parseApiJson not found');
const sandbox = { window: {} };
vm.createContext(sandbox);
vm.runInContext(match[0], sandbox);
const parseApiJson = sandbox.parseApiJson;

(async () => {
  const mkResp = (status, body, opts = {}) => ({
    status,
    redirected: !!opts.redirected,
    headers: { get: (k) => (k.toLowerCase() === 'content-type' ? (opts.ct || 'text/html') : '') },
    text: async () => body,
  });

  // 1. Valid JSON
  const ok = await parseApiJson(mkResp(200, JSON.stringify({ success: true }), { ct: 'application/json' }), 'Save');
  if (!ok.success) throw new Error('expected ok.success');

  // 2. Redirected HTML login page (302 -> 200 <!DOCTYPE html>)
  sandbox.window._lastAuthExpiredAt = 0;
  let caught = null;
  try {
    await parseApiJson(mkResp(200, '<!DOCTYPE html><html></html>', { redirected: true }), 'Save');
  } catch (e) { caught = e; }
  if (!caught || caught instanceof SyntaxError || !sandbox.window._lastAuthExpiredAt) {
    throw new Error('expected friendly auth error, got: ' + caught);
  }

  // 3. Proxy 502 HTML gateway error
  let caught502 = null;
  try {
    await parseApiJson(mkResp(502, '<html>502 Bad Gateway</html>'), 'Start');
  } catch (e) { caught502 = e; }
  if (!caught502 || !String(caught502.message).includes('HTTP 502')) {
    throw new Error('expected 502 message, got: ' + caught502);
  }

  // 4. Backend 401 JSON auth_expired
  sandbox.window._lastAuthExpiredAt = 0;
  const expired = await parseApiJson(
    mkResp(401, JSON.stringify({ success: false, auth_expired: true, error: 'Session expired' }), { ct: 'application/json' }),
    'Start'
  );
  if (expired.success !== false || !sandbox.window._lastAuthExpiredAt) {
    throw new Error('expected 401 JSON auth_expired flag');
  }
  console.log('ALL_OK');
})();
"""
        proc = subprocess.run(["node", "-e", script], cwd=REPO, capture_output=True, text=True, timeout=15)
        assert proc.returncode == 0, proc.stderr
        assert "ALL_OK" in proc.stdout

