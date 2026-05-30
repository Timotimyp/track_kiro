const { app, BrowserWindow, shell } = require('electron')

// URL of your deployed TaskFlow frontend
const APP_URL = 'https://blue-river-0de0d5200.7.azurestaticapps.net'

function createWindow() {
  const win = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 380,
    minHeight: 600,
    title: 'TaskFlow',
    titleBarStyle: 'hiddenInset',
    trafficLightPosition: { x: 16, y: 16 },
    backgroundColor: '#0f0f11',
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
    },
    show: false,
  })

  win.loadURL(APP_URL)

  win.once('ready-to-show', () => {
    win.show()
  })

  // Allow Microsoft login popups, open everything else in default browser
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (url.includes('login.microsoftonline.com') || url.includes('login.live.com')) {
      return { action: 'allow' }
    }
    shell.openExternal(url)
    return { action: 'deny' }
  })

  win.webContents.on('will-navigate', (event, url) => {
    const appHost = new URL(APP_URL).host
    const navHost = new URL(url).host
    if (navHost !== appHost && !url.includes('login.microsoftonline.com') && !url.includes('login.live.com')) {
      event.preventDefault()
      shell.openExternal(url)
    }
  })
}

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow()
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})

app.whenReady().then(createWindow)
