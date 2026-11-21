--[[ Library > Plug-in Extras > Calotype Bridge starten ]]

local LrDialogs = import "LrDialogs"
local LrTasks = import "LrTasks"

local BridgeClient = require "BridgeClient"

local TITLE = LOC "$$$/Calotype/Menu/StartBridge=Calotype Bridge starten"

LrTasks.startAsyncTask(function()
  local health = BridgeClient.health()
  if health then
    LrDialogs.message(TITLE, string.format("Die Calotype Bridge läuft bereits auf 127.0.0.1 (Version %s).", health.version or "ok"), "info")
    return
  end

  local started = BridgeClient.startBridge()
  if not started then
    LrDialogs.message(TITLE, "Start-Calotype-Bridge.cmd konnte nicht gefunden werden.", "warning")
    return
  end

  -- Wait up to 10 seconds for the bridge to come online
  for _ = 1, 10 do
    LrTasks.sleep(1)
    health = BridgeClient.health()
    if health then
      LrDialogs.message(TITLE, string.format("Calotype Bridge wurde erfolgreich gestartet (Version %s)!", health.version or "ok"), "info")
      return
    end
  end

  LrDialogs.message(TITLE, "Die Bridge wurde aufgerufen, antwortet aber noch nicht. Bitte kurz warten und Status prüfen.", "info")
end)
