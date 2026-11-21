--[[ Library > Plug-in Extras > Bridge status... ]]

local LrDialogs = import "LrDialogs"
local LrTasks = import "LrTasks"

local Automation = require "AutomationState"
local BridgeClient = require "BridgeClient"

local TITLE = LOC "$$$/Calotype/Status/Title=Calotype Bridge"

LrTasks.startAsyncTask(function()
  local cfg, cfgErr, path = BridgeClient.loadConfig()
  if not cfg then
    LrDialogs.message(TITLE, cfgErr, "warning")
    return
  end

  local health, err = BridgeClient.health()
  if not health then
    LrDialogs.message(TITLE, err .. "\n\n" .. LOC("$$$/Calotype/Status/Settings=Settings: ^1", path), "warning")
    return
  end

  local lines = {
    LOC("$$$/Calotype/Status/Running=Bridge ^1 is running on 127.0.0.1:^2.", health.version or "?", cfg.port),
    LOC("$$$/Calotype/Status/Server=Server: ^1", tostring(cfg.api_base_url)),
  }
  local profiles, profilesErr = BridgeClient.profiles()
  if profiles then
    local ready = 0
    for _, p in ipairs(profiles) do
      if p.status == "ready" then ready = ready + 1 end
    end
    lines[#lines + 1] = LOC("$$$/Calotype/Status/Profiles=Profiles: ^1 ready, ^2 in total.", ready, #profiles)
  else
    lines[#lines + 1] = LOC("$$$/Calotype/Status/ServerDown=Server not reachable — jobs wait in the Bridge queue. (^1)", profilesErr)
  end
  if Automation.enabled then
    lines[#lines + 1] = LOC "$$$/Calotype/Status/Automation=Automation channel is ON (test mode)."
  end
  lines[#lines + 1] = LOC("$$$/Calotype/Status/Settings=Settings: ^1", path)
  LrDialogs.message(TITLE, table.concat(lines, "\n"), "info")
end)
