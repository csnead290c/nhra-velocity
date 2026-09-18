from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_hidden_launcher_is_offline_first_and_does_not_mutate_install():
    vbs = (ROOT / 'scripts' / 'Launch-NHRA-Velocity-Dev.vbs').read_text(encoding='utf-8').lower()
    cmd = (ROOT / 'scripts' / 'Launch-NHRA-Velocity-Dev.cmd').read_text(encoding='utf-8').lower()
    combined = vbs + "\n" + cmd
    assert 'git fetch' not in combined
    assert 'git pull' not in combined
    assert 'pip install' not in combined
    assert 'pythonw.exe' in vbs
    assert 'desktop.py' in vbs
    # Normal startup must not put Qt behind a hidden cmd.exe parent.
    assert 'cmd.exe /d' not in vbs
    assert 'shell.run(command, 1, true)' in vbs


def test_visible_diagnostic_launcher_exists():
    text = (ROOT / 'scripts' / 'Launch-NHRA-Velocity-Diagnostic.cmd').read_text(encoding='utf-8').lower()
    assert 'python.exe' in text
    assert 'desktop.py' in text
    assert 'pause' in text


def test_shortcut_targets_direct_vbs_launcher():
    text = (ROOT / 'scripts' / 'Create-NHRA-Velocity-Dev-Shortcut.ps1').read_text(encoding='utf-8').lower()
    assert 'launch-nhra-velocity-dev.vbs' in text
    assert 'wscript.exe' in text
    assert 'auto-update launcher' not in text


def test_protected_startup_shows_shell_before_sign_in():
    text = (ROOT / 'desktop.py').read_text(encoding='utf-8')
    marker = "logging.info('Tech Services sign-in required before protected startup')"
    i = text.index(marker)
    j = text.index('if not win._sign_in():', i)
    block = text[i:j]
    assert 'win.show()' in block
    assert 'app.processEvents()' in block
