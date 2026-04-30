"""Security regression tests for P1 fixes (commit session)."""

import sys
import threading
import unittest
from pathlib import Path

# Ensure project root on path
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

sys.path.insert(0, str(PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Test 1: url_safety SSRF blocklist
# ---------------------------------------------------------------------------
class TestUrlSafety(unittest.TestCase):
    def _call(self, url):
        import importlib.util
        spec = importlib.util.spec_from_file_location("url_safety", "tools/url_safety.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        safe, reason = mod.is_safe_url(url)
        block = mod.maybe_block_url(url)
        return safe, reason, block

    def test_public_url_is_safe(self):
        safe, reason, _ = self._call("https://example.com/path?q=1")
        self.assertTrue(safe, f"Public URL blocked: {reason}")

    def test_http_public_url_is_safe(self):
        safe, reason, _ = self._call("http://example.com")
        self.assertTrue(safe, f"HTTP public URL blocked: {reason}")

    def test_loopback_blocked(self):
        safe, _, block = self._call("http://127.0.0.1:8000")
        self.assertFalse(safe)
        self.assertIn("127.0.0.1", block["error"])

    def test_rfc1918_10_blocked(self):
        safe, _, _ = self._call("https://10.0.0.1/admin")
        self.assertFalse(safe)

    def test_rfc1918_172_blocked(self):
        safe, _, _ = self._call("https://172.16.0.1/admin")
        self.assertFalse(safe)

    def test_rfc1918_192_blocked(self):
        safe, _, _ = self._call("https://192.168.1.1/admin")
        self.assertFalse(safe)

    def test_link_local_blocked(self):
        safe, _, _ = self._call("http://169.254.169.254/latest/meta-data")
        self.assertFalse(safe)

    def test_link_local_variant_blocked(self):
        safe, _, _ = self._call("http://169.254.169.254/metadata/v1")
        self.assertFalse(safe)

    def test_localhost_blocked(self):
        for host in ("localhost", "LOCALHOST", "LocalHost"):
            safe, _, _ = self._call(f"https://{host}/api")
            self.assertFalse(safe, f"{host} should be blocked")

    def test_internal_hostname_blocked(self):
        safe, _, _ = self._call("https://api.internal/health")
        self.assertFalse(safe)

    def test_metadata_hostname_blocked(self):
        safe, _, _ = self._call("https://metadata.google.internal")
        self.assertFalse(safe)

    def test_ipv6_loopback_blocked(self):
        safe, _, _ = self._call("https://[::1]/admin")
        self.assertFalse(safe)

    def test_cidr_cogent_blocked(self):
        safe, _, _ = self._call("http://100.100.100.200/")  # Alibaba metadata
        self.assertFalse(safe)

    def test_scheme_allowlist_blocks_ftp(self):
        safe, _, _ = self._call("ftp://example.com/file.txt")
        self.assertFalse(safe)

    def test_bidi_stripped_not_blocked(self):
        safe, reason, _ = self._call("https://example.com/path\u200e")
        self.assertTrue(safe, f"Bidi-stripped URL wrongly blocked: {reason}")


# ---------------------------------------------------------------------------
# Test 2: sudo password thread-local isolation
# ---------------------------------------------------------------------------
class TestSudoThreadIsolation(unittest.TestCase):
    def test_cached_password_is_thread_local(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("terminal_tool_mod", "tools/terminal_tool.py")
        tt = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tt)

        # Simulate thread A caching a password
        tt._thread_local.sudo_password = "thread_a_secret"

        # Spawn thread B — should NOT see thread A's cached password
        result_b = []

        def thread_b():
            result_b.append(getattr(tt._thread_local, "sudo_password", None))

        t = threading.Thread(target=thread_b)
        t.start()
        t.join()

        self.assertEqual(result_b[0], None,
                         "Thread B leaked Thread A's cached sudo password")

        # Clean up
        del tt._thread_local.sudo_password

    def test_own_thread_retains_password(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("terminal_tool_mod", "tools/terminal_tool.py")
        tt = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tt)
        tt._thread_local.sudo_password = "my_secret"
        self.assertEqual(getattr(tt._thread_local, "sudo_password", None), "my_secret")
        del tt._thread_local.sudo_password


# ---------------------------------------------------------------------------
# Test 3: redaction now covers OLLAMA_API_KEY
# ---------------------------------------------------------------------------
class TestRedactionPatterns(unittest.TestCase):
    def test_ollama_api_key_env_redacted(self):
        from agent.redact import redact_sensitive_text
        text = "OLLAMA_API_KEY=sk-ollama-1234567890abcdef"
        result = redact_sensitive_text(text)
        self.assertIn("***", result)
        self.assertNotIn("sk-ollama-1234567890abcdef", result)

    def test_generic_api_key_env_redacted(self):
        from agent.redact import redact_sensitive_text
        text = "MY_API_KEY=somevalue12345"
        result = redact_sensitive_text(text)
        self.assertIn("***", result)

    def test_openai_key_redacted(self):
        from agent.redact import redact_sensitive_text
        text = "Authorization: Bearer sk-abc123456789012345678901"
        result = redact_sensitive_text(text)
        self.assertIn("***", result)
        self.assertNotIn("sk-abc123456789012345678901", result)

    def test_non_secret_untouched(self):
        from agent.redact import redact_sensitive_text
        text = "USER_NAME=john_doe"
        result = redact_sensitive_text(text)
        self.assertEqual(result, text)


# ---------------------------------------------------------------------------
# Test 4: MCP OAuth state generation and verification
# ---------------------------------------------------------------------------
class TestMcpOAuthState(unittest.TestCase):
    def test_state_generated_succeeds(self):
        from tools.mcp_oauth import _generate_state
        state1 = _generate_state()
        state2 = _generate_state()
        self.assertIsInstance(state1, str)
        self.assertTrue(len(state1) >= 32)
        self.assertNotEqual(state1, state2)

    def test_state_store_and_verify(self):
        from tools.mcp_oauth import _store_state, _verify_and_clear_state
        _store_state("test_server", "expected_state_123")
        self.assertTrue(_verify_and_clear_state("test_server", "expected_state_123"))

    def test_state_mismatch_fails(self):
        from tools.mcp_oauth import _store_state, _verify_and_clear_state
        _store_state("test_server2", "correct_state")
        self.assertFalse(_verify_and_clear_state("test_server2", "wrong_state"))

    def test_state_one_time_use(self):
        from tools.mcp_oauth import _store_state, _verify_and_clear_state
        _store_state("test_server3", "one_time")
        self.assertTrue(_verify_and_clear_state("test_server3", "one_time"))
        # Second verification must fail (already cleared)
        self.assertFalse(_verify_and_clear_state("test_server3", "one_time"))


# ---------------------------------------------------------------------------
# Test 5: TUI approval defaults to deny
# ---------------------------------------------------------------------------
class TestTuiApprovalDefault(unittest.TestCase):
    """Verify the approval prompt defaults to 'deny' (last index) so accidental
    keypresses don't approve dangerous commands."""

    def test_approval_choices_order(self):
        # Import cli.py via importlib to avoid full init cascade
        try:
            import cli as cli_mod
        except Exception:
            self.skipTest("cli.py requires heavy deps not available in test env")
        # _approval_choices is a simple helper that doesn't depend on self
        choices = cli_mod.CLI._approval_choices(None, "some_command", allow_permanent=True)
        self.assertEqual(choices[-1], "deny")
        self.assertEqual(len(choices), 5)

    def test_default_selected_is_deny(self):
        try:
            import cli as cli_mod
        except Exception:
            self.skipTest("cli.py requires heavy deps not available in test env")
        choices = cli_mod.CLI._approval_choices(None, "cmd", allow_permanent=True)
        self.assertEqual(choices[len(choices) - 1], "deny")


if __name__ == "__main__":
    unittest.main(verbosity=2)
