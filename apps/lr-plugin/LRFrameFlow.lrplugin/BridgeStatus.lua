--[[ Library > Plug-in Extras > Bridge status... ]]

local LrDialogs = import "LrDialogs"
local LrTasks = import "LrTasks"

local BridgeClient = require "BridgeClient"

LrTasks.startAsyncTask(function()
  local cfg, cfgErr, path = BridgeClient.loadConfig()
  if not cfg then
    LrDialogs.message("LR-FrameFlow Bridge", cfgErr, "warning")
    return
  end

  local health, err = BridgeClient.health()
  if not health then
    LrDialogs.message("LR-FrameFlow Bridge", err .. "\n\nSettings: " .. path, "warning")
    return
  end

  local lines = {
    string.format("Bridge %s is running on 127.0.0.1:%d.", health.version or "?", cfg.port),
    "Server: " .. tostring(cfg.api_base_url),
  }
  local profiles, profilesErr = BridgeClient.profiles()
  if profiles then
    local ready = 0
    for _, p in ipairs(profiles) do
      if p.status == "ready" then ready = ready + 1 end
    end
    lines[#lines + 1] = string.format("Profiles: %d ready, %d in total.", ready, #profiles)
  else
    lines[#lines + 1] = "Server not reachable — jobs wait in the Bridge queue. (" .. profilesErr .. ")"
  end
  lines[#lines + 1] = "Settings: " .. path
  LrDialogs.message("LR-FrameFlow Bridge", table.concat(lines, "\n"), "info")
end)
