const invoke = window.__TAURI__?.core?.invoke;

const statusOutput = document.getElementById('status-output');
const btnStatus = document.getElementById('btn-status');
const btnStart = document.getElementById('btn-start');
const btnStop = document.getElementById('btn-stop');
const btnRestart = document.getElementById('btn-restart');
const btnOpen = document.getElementById('btn-open');
const btnLog = document.getElementById('btn-log');
const btnExit = document.getElementById('btn-exit');
const allButtons = [btnStatus, btnStart, btnStop, btnRestart, btnOpen, btnLog, btnExit];

const LINE_MAX = 110;
const DOT_DIVIDER = '.'.repeat(LINE_MAX);
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

/** 将 monitor_ctl.sh status 的单行输出格式化为多行展示 */
function formatServiceStatusOutput(raw) {
  const text = String(raw ?? '').trim();
  if (!text) {
    return ['无输出'];
  }
  if (text.includes('运行中')) {
    const lines = ['服务启动成功🎉, 点击-打开面板-即可管理喜欢的主播💗', DOT_DIVIDER];
    const pidMatch = text.match(/pid=(\d+)/);
    const urlMatch = text.match(/(https?:\/\/[^\s]+)/);
    const logMatch = text.match(/日志:\s*(.+)$/);
    if (pidMatch) {
      lines.push(`运行中 pid=${pidMatch[1]}`);
    }
    if (urlMatch) {
      lines.push(urlMatch[1]);
    }
    if (logMatch) {
      lines.push(`日志: ${logMatch[1].trim()}`);
    }
    if (lines.length === 1) {
      lines.push(text.replace(/^运行中\s*/, '').trim() || text);
    }
    return lines;
  }
  const lines = text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  return lines.length ? lines : ['无输出'];
}

function setStatusText(text) {
  setStatusLines(formatServiceStatusOutput(text));
}

function boolIcon(value) {
  return value ? '✅' : '❌';
}

function formatSetupStatus(status) {
  const boot = status?.pythonUsableForBootstrap;
  const message = status?.message ? String(status.message).replace(/\s*\n+\s*/g, ' / ') : '';
  const lines = [];
  if (message) {
    lines.push(`提示: ${message}`);
    lines.push(DOT_DIVIDER);
  }
  lines.push(
    `环境就绪: ${boolIcon(Boolean(status?.ready))}`,
    `Python: ${boot === true ? '✅' : boot === false ? '❌' : '❌'}`,
    `虚拟环境: ${boolIcon(Boolean(status?.venvExists))}`,
    `依赖安装: ${boolIcon(Boolean(status?.depsInstalled))}`,
    `Playwright Chromium: ${boolIcon(Boolean(status?.playwrightChromiumInstalled))}`,
  );
  return lines;
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
  return setup;
}

async function refreshStatus() {
  try {
    const output = await invoke('service_status');
    setStatusText(output || '无输出');
  } catch (err) {
    const text = String(err ?? '').trim();
    if (text.includes('未运行')) {
      setStatusLines(['服务状态: 未运行']);
      return;
    }
    setStatusLines([`状态获取失败: ${text}`]);
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
    const percent = Math.min(95, 15 + elapsed * 2);
    const dots = '.'.repeat((elapsed % 3) + 1);
    const barWidth = 24;
    const filled = Math.max(1, Math.floor((percent / 100) * barWidth));
    const bar = `${'█'.repeat(filled)}${'·'.repeat(Math.max(0, barWidth - filled))}`;
    setStatusLines([
      `${INSTALL_PROGRESS_STEPS[stepIndex]}${dots}`,
      `进度: [${bar}] ${percent}%`,
      `已耗时: ${elapsed}s（首次安装通常需要几分钟）`,
    ]);
  }, 1000);
  return () => clearInterval(timer);
}

if (!invoke) {
  setStatusLines(['Tauri API 不可用。请通过 `npm run dev` 或打包后的 App 运行。']);
  throw new Error('Tauri API unavailable');
}

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

btnStatus.addEventListener('click', refreshStatus);
btnStart.addEventListener('click', async () => {
  let setup = await getSetupStatus(false);
  if (setup && setup.embeddedPythonAvailable === false) {
    setStatusLines(['无法启动：应用内置 Python 不可用，请重装应用。', ...formatSetupStatus(setup)]);
    return;
  }
  if (setup && !setup.ready) {
    setButtonsDisabled(true);
    setStatusLines(['环境未就绪，正在自动安装依赖与 Chromium...']);
    const stopTicker = startInstallProgressTicker();
    try {
      await invoke('setup_install');
      stopTicker();
      setup = await getSetupStatus(false);
      if (!setup || !setup.ready) {
        setStatusLines(['自动安装完成，但环境仍未就绪。', ...(setup ? formatSetupStatus(setup) : [])]);
        return;
      }
      setStatusLines(['自动安装完成，正在启动服务...', ...formatSetupStatus(setup)]);
    } catch (err) {
      stopTicker();
      setStatusLines([`自动安装失败: ${String(err)}`]);
      return;
    } finally {
      stopTicker();
      setButtonsDisabled(false);
    }
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
