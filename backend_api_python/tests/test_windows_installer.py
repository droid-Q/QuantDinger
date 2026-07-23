from pathlib import Path


def test_passwordless_mt5_backend_uses_interactive_logon_task():
    script = (
        Path(__file__).parents[2]
        / "scripts"
        / "windows"
        / "install-mt5-windows-service.ps1"
    ).read_text(encoding="utf-8")

    assert "[switch]$Passwordless" in script
    assert "[switch]$WindowsService" in script
    assert "Install-BackendLogonTask" in script
    assert "-LogonType Interactive" in script
    assert "-SessionRun" in script
    assert "$usePasswordless = -not $WindowsService" in script
    assert "if ($usePasswordless)" in script
