# Release quantdinger-mcp to PyPI

## This release: 0.4.0

This is the v5 contract release. It replaces the 0.3 legacy strategy and experiment surface with Strategy API V2 source management, manifest compilation, version history, native order protection, runtime controls, and authenticated network transports.

Before uploading:

- configure and test a distinct `QUANTDINGER_MCP_AUTH_TOKEN` for every public HTTP deployment;
- verify the Strategy API V2 source, compile, backtest, and stopped-deployment workflow;
- rebuild from a clean directory so no 0.3 artifacts are present.

```powershell
cd mcp_server

# 1. Install build tools (once)
py -3.13 -m pip install -e ".[dev]"

# 2. Tests
py -3.13 -m pytest tests/ -q

# 3. Clean old artifacts (optional)
Remove-Item -Recurse -Force dist, build -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force src\quantdinger_mcp.egg-info -ErrorAction SilentlyContinue

# 4. Build
py -3.13 -m build

# 5. Upload (you run this -- needs your PyPI token)
$env:TWINE_USERNAME = "__token__"
$env:TWINE_PASSWORD = "pypi-Ag..."   # your API token
py -3.13 -m twine upload dist/quantdinger_mcp-0.4.0*

# 6. Verify
pip install --upgrade "quantdinger-mcp==0.4.0"
quantdinger-mcp
```

Linux / macOS upload:

```bash
cd mcp_server
pip install -e ".[dev]"
python -m pytest tests/ -q
rm -rf dist build src/*.egg-info
python -m build
TWINE_USERNAME=__token__ TWINE_PASSWORD=pypi-... python -m twine upload dist/quantdinger_mcp-0.4.0*
```

## Notes

- Upload **only** the `0.4.0` files from `dist/` -- do not upload older versions again.
- PyPI token: Account settings -> API tokens -> scope `quantdinger-mcp` or entire account.
- After publish: restart Cursor MCP or `pip install --upgrade quantdinger-mcp`.
