--[[ LrInitPlugin: starts the automation channel when bridge.json says "automation": true.

Off by default. When on, the plugin asks the Bridge every two seconds for a test command
(GET /v1/automation/next), runs it with AutomationCommands and posts the result back.

Lightroom specifics this file is built around (each one found in a real run):
- Reading an undefined global raises an error: this file uses no globals at all.
- On "Reload Plug-in" the new plugin starts before the old one is unloaded: every start
  takes a new generation number (kept in the plugin prefs) and a loop runs only while its
  number is current, so an old loop ends by itself.
- Catalog and HTTP calls yield; plain pcall cannot yield, LrTasks.pcall can. ]]

local LrApplication = import "LrApplication"
local LrDialogs = import "LrDialogs"
local LrPrefs = import "LrPrefs"
local LrTasks = import "LrTasks"

-- Loaded here, not inside the task: the only start that ever worked in Lightroom did so.
local AutomationCommands = require "AutomationCommands"
local AutomationState = require "AutomationState"
local BridgeClient = require "BridgeClient"
local Log = require "Log"

-- The generation lives in the plugin's prefs, not in a global: Lightroom raises an
-- error when an undefined global is read.
local prefs = LrPrefs.prefsForPlugin()
local generation = (tonumber(prefs.automationGeneration) or 0) + 1
prefs.automationGeneration = generation
Log.info("plugin init (automation generation %d)", generation)

local function current()
  return prefs.automationGeneration == generation
end

LrTasks.startAsyncTask(function()
  local started, startErr = LrTasks.pcall(function()
    local cfg, cfgErr = BridgeClient.loadConfig()
    if not cfg then
      Log.warn("automation: no bridge config (%s)", tostring(cfgErr))
      return
    end
    if cfg.automation ~= true then return end
    AutomationState.enabled = true
    Log.info("automation channel on (generation %d)", generation)

    local function step()
      local command, err = BridgeClient.automationNext()
      if not current() then return end -- a newer plugin took over while we were waiting
      if command == BridgeClient.NO_CONTENT then
        LrTasks.sleep(2)
      elseif command then
        Log.info("automation: %s #%s", tostring(command.command), tostring(command.id))
        local ok, result = AutomationCommands.run(LrApplication.activeCatalog(), command)
        local _, postErr = BridgeClient.automationResult(command.id, ok, result)
        if postErr then Log.warn("automation: result not delivered: %s", postErr) end
      else
        Log.warn("automation: %s", tostring(err))
        LrTasks.sleep(5)
      end
    end

    while current() do
      -- One failing step must never end the channel.
      local ok, err = LrTasks.pcall(step)
      if not ok then
        Log.warn("automation step failed: %s", tostring(err))
        LrTasks.sleep(5)
      end
    end
    Log.info("automation channel of generation %d ended", generation)
  end)
  if not started then
    LrDialogs.message("Tarsier", "Automation channel failed to start: " .. tostring(startErr), "critical")
  end
end)
