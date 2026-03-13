// Smart Home Temperature Widget for Scriptable
// https://scriptable.app
//
// Setup:
//   1. Install Scriptable from the App Store
//   2. Create a new script and paste this file's contents
//   3. Set SERVER_URL to your smart-home server's IP address
//   4. Add a Scriptable widget to your home screen and select this script

const SERVER_URL = "http://192.168.1.100:5000"

// ── Fetch data ────────────────────────────────────────────────────────────────

let sensors = []
let fetchError = null

try {
  const req = new Request(`${SERVER_URL}/api/current`)
  req.timeoutInterval = 10
  sensors = await req.loadJSON()
} catch (e) {
  fetchError = e.message
}

// ── Build widget ──────────────────────────────────────────────────────────────

const BG       = new Color("#f0f4f8")
const TEXT     = new Color("#1a2535")
const MUTED    = new Color("#7a90a8")
const ORANGE   = new Color("#e07820")
const BLUE     = new Color("#2e7dd4")
const DIVIDER  = new Color("#e0e8f0")

const widget = new ListWidget()
widget.backgroundColor = BG
widget.setPadding(14, 16, 12, 16)

// Title row
const titleRow = widget.addStack()
titleRow.layoutHorizontally()
titleRow.centerAlignContent()

const title = titleRow.addText("Smart Home")
title.font = Font.boldSystemFont(15)
title.textColor = TEXT

titleRow.addSpacer()

const now = new Date()
const timeStr = now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
const updatedText = titleRow.addText(timeStr)
updatedText.font = Font.systemFont(11)
updatedText.textColor = MUTED

widget.addSpacer(10)

if (fetchError) {
  const err = widget.addText("Could not reach server")
  err.font = Font.systemFont(12)
  err.textColor = new Color("#c0392b")
  widget.addSpacer()
} else if (sensors.length === 0) {
  const msg = widget.addText("No sensors found")
  msg.font = Font.systemFont(12)
  msg.textColor = MUTED
  widget.addSpacer()
} else {
  for (let i = 0; i < sensors.length; i++) {
    const s = sensors[i]

    const row = widget.addStack()
    row.layoutHorizontally()
    row.centerAlignContent()

    // Label
    const label = row.addText((s.label || s.address).toUpperCase())
    label.font = Font.boldSystemFont(11)
    label.textColor = MUTED
    label.lineLimit = 1

    row.addSpacer()

    // Temperature
    const temp = row.addText(`${s.temp_f.toFixed(1)}°F`)
    temp.font = Font.boldSystemFont(16)
    temp.textColor = ORANGE

    row.addSpacer(10)

    // Humidity
    const hum = row.addText(`${s.humidity.toFixed(1)}%`)
    hum.font = Font.systemFont(14)
    hum.textColor = BLUE

    // Divider between rows (not after last)
    if (i < sensors.length - 1) {
      widget.addSpacer(6)
      const div = widget.addStack()
      div.backgroundColor = DIVIDER
      div.size = new Size(0, 1)
      widget.addSpacer(6)
    }
  }
  widget.addSpacer()
}

Script.setWidget(widget)
await widget.presentMedium()
Script.complete()
