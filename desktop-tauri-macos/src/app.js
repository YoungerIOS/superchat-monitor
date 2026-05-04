const invoke = window.__TAURI__?.core?.invoke;

const statusOutput = document.getElementById('status-output');
const btnSetup = document.getElementById('btn-setup');
const btnPythonDl = document.getElementById('btn-python-dl');
const btnStatus = document.getElementById('btn-status');
const btnStart = document.getElementById('btn-start');
const btnStop = document.getElementById('btn-stop');
const btnRestart = document.getElementById('btn-restart');
const btnOpen = document.getElementById('btn-open');
const btnLog = document.getElementById('btn-log');
const btnExit = document.getElementById('btn-exit');
const allButtons = [btnSetup, btnStatus, btnStart, btnStop, btnRestart, btnOpen, btnLog, btnExit];

const LINE_MAX = 110;
const INSTALL_PROGRESS_STEPS = [
  '安装依赖：准备环境',
  '安装依赖：创建虚拟环境',
  '安装依赖：下载 Python 包',
  '安装依赖：安装 Chromium',
];

function setButtonsDisabled(disabled) {
  for (const button of allButtons) {
    button.disabled = disabled;
  }
}

function truncateLine(text, max = LINE_MAX) {
  const value = String(text ?? '').replace(/\s+/g, ' ').trim();
  if (!value) {
    return '';
  }
  return value.length > max ? `${value.slice(0, Math.max(0, max - 1))}…` : value;
}

function setStatusLines(lines) {
  statusOutput.innerHTML = '';
  for (const line of lines) {
    const el = document.createElement('div');
    el.className = 'status-line';
    const clean = truncateLine(line);
    el.textContent = clean || '-';
    el.title = String(line ?? '');
    statusOutput.appendChild(el);
  }
}

function setStatusText(text) {
  const lines = String(text ?? '')
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  setStatusLines(lines.length ? lines : ['无输出']);
}

function boolIcon(value) {
  return value ? '✅' : '❌';
}

function formatSetupStatus(status) {
  const boot = status?.pythonUsableForBootstrap;
  const message = status?.message ? String(status.message).replace(/\s*\n+\s*/g, ' / ') : '';
  const lines = [
    `环境就绪: ${boolIcon(Boolean(status?.ready))}`,
    `检测到 Python: ${boot === true ? '✅' : boot === false ? '❌' : '❌'}`,
    `Python: ${status?.python || '未找到'}`,
    `虚拟环境(.venv-desktop): ${boolIcon(Boolean(status?.venvExists))}`,
    `依赖安装: ${boolIcon(Boolean(status?.depsInstalled))}`,
    `Playwright Chromium: ${boolIcon(Boolean(status?.playwrightChromiumInstalled))}`,
  ];
  if (message) {
    lines.push(`提示: ${message}`);
  }
  return lines;
}

function syncPythonDownloadButton(setup) {
  if (!btnPythonDl || !setup) {
    return;
  }
  const show = setup.pythonUsableForBootstrap === false;
  btnPythonDl.hidden = !show;
}

async function getSetupStatus(showError = true) {
  try {
    return await invoke('setup_check');
  } catch (err) {
    if (showError) {
      setStatusLines([`环境检查失败: ${String(err)}`]);
    }
    return null;
  }
}

async function refreshSetupSummary() {
  const setup = await getSetupStatus(true);
  if (!setup) {
    return null;
  }
  setStatusLines(formatSetupStatus(setup));
  syncPythonDownloadButton(setup);
  return setup;
}

async function refreshStatus() {
  try {
    const output = await invoke('service_status');
    setStatusText(output || '无输出');
  } catch (err) {
    setStatusLines([`状态获取失败: ${String(err)}`]);
  }
}

async function runAction(fn, busyText) {
  setStatusLines([busyText]);
  try {
    await fn();
  } catch (err) {
    setStatusLines([`执行失败: ${String(err)}`]);
    return;
  }
  await refreshStatus();
}

function startInstallProgressTicker() {
  const started = Date.now();
  const timer = setInterval(() => {
    const elapsed = Math.floor((Date.now() - started) / 1000);
    const stepIndex = Math.min(Math.floor(elapsed / 20), INSTALL_PROGRESS_STEPS.length - 1);
    const dots = '.'.repeat((elapsed % 3) + 1);
    setStatusLines([
      `${INSTALL_PROGRESS_STEPS[stepIndex]}${dots}`,
      `已耗时: ${elapsed}s（首次安装通常需要几分钟）`,
    ]);
  }, 1000);
  return () => clearInterval(timer);
}

if (!invoke) {
  setStatusLines(['Tauri API 不可用。请通过 `npm run dev` 或打包后的 App 运行。']);
  throw new Error('Tauri API unavailable');
}

btnPythonDl.addEventListener('click', async () => {
  try {
    await invoke('open_python_downloads');
    await refreshSetupSummary();
  } catch (err) {
    setStatusLines([`无法打开下载页: ${String(err)}`]);
  }
});

/** 说明区外链：Tauri WebView 不会自动处理 target="_blank"。 */
document.querySelector('.tips')?.addEventListener('click', async (e) => {
  let el = e.target;
  if (el.nodeType === Node.TEXT_NODE) {
    el = el.parentElement;
  }
  const a = el?.closest?.('a');
  if (!a || !a.href) {
    return;
  }
  try {
    const u = new URL(a.href);
    if (u.protocol !== 'https:') {
      return;
    }
  } catch {
    return;
  }
  e.preventDefault();
  try {
    await invoke('open_external_url', { url: a.href });
  } catch (err) {
    setStatusLines([`无法打开链接: ${String(err)}`]);
  }
});

btnSetup.addEventListener('click', async () => {
  const pre = await getSetupStatus(false);
  if (pre && pre.pythonUsableForBootstrap === false) {
    setStatusLines(['无法开始安装依赖：本机没有可用的 Python 3。', ...formatSetupStatus(pre)]);
    syncPythonDownloadButton(pre);
    return;
  }
  setButtonsDisabled(true);
  setStatusLines(['安装依赖：准备开始...']);
  const stopTicker = startInstallProgressTicker();
  try {
    await invoke('setup_install');
    stopTicker();
    const setup = await getSetupStatus(false);
    if (setup) {
      setStatusLines(formatSetupStatus(setup));
      syncPythonDownloadButton(setup);
    } else {
      setStatusLines(['安装依赖已完成。']);
    }
  } catch (err) {
    stopTicker();
    setStatusLines([`安装依赖失败: ${String(err)}`]);
  } finally {
    stopTicker();
    setButtonsDisabled(false);
  }
});

btnStatus.addEventListener('click', refreshStatus);
btnStart.addEventListener('click', async () => {
  const setup = await getSetupStatus(false);
  if (setup && setup.pythonUsableForBootstrap === false) {
    setStatusLines(['无法启动：请先安装 Python 3.9+（可点击「打开 Python 官网」）。', ...formatSetupStatus(setup)]);
    syncPythonDownloadButton(setup);
    return;
  }
  if (setup && !setup.ready) {
    setStatusLines(['环境未就绪，请先点击“安装依赖”。', ...formatSetupStatus(setup)]);
    syncPythonDownloadButton(setup);
    return;
  }
  await runAction(() => invoke('service_start'), '正在启动服务...');
});
btnStop.addEventListener('click', () => runAction(() => invoke('service_stop'), '正在停止服务...'));
btnRestart.addEventListener('click', () => runAction(() => invoke('service_restart'), '正在重启服务...'));
btnOpen.addEventListener('click', async () => {
  await runAction(() => invoke('service_open_panel'), '正在打开面板...');
});
btnLog.addEventListener('click', async () => {
  await runAction(() => invoke('service_open_log'), '正在打开日志文件...');
});
btnExit.addEventListener('click', async () => {
  setButtonsDisabled(true);
  setStatusLines(['正在停止后台服务...']);
  try {
    const stopOutput = await invoke('service_stop');
    const lines = String(stopOutput || '已停止').split(/\r?\n/).filter(Boolean);
    setStatusLines([...lines, '后台服务已停止，正在退出桌面程序...']);
    await invoke('app_exit');
  } catch (err) {
    setButtonsDisabled(false);
    setStatusLines([`退出失败: ${String(err)}`]);
  }
});

refreshSetupSummary();
