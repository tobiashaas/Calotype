--[[ HTTP client for the local Bridge (packages/contracts/openapi/plugin-bridge-api.yaml).

Port and token come from bridge.json, which the Bridge writes on first start.
Every function returns `result, errorMessage`. Call only from an async task.
]]

local LrFileUtils = import "LrFileUtils"
local LrHttp = import "LrHttp"
local LrPathUtils = import "LrPathUtils"

local Json = require "Json"
local Log = require "Log"

local BridgeClient = {}

--- Returned instead of a body for "204 No Content" (e.g. no automation command waiting).
BridgeClient.NO_CONTENT = setmetatable({}, { __tostring = function() return "no content" end })

local CONFIG_DIR = "LRFrameFlow"
local CONFIG_FILE = "bridge.json"
local NOT_RUNNING = LOC "$$$/LRFrameFlow/Bridge/NotRunning=The LR-FrameFlow Bridge is not running. Start the Bridge app and try again."

-- Lightroom's Lua sandbox has no os.getenv (and may lack `os` entirely): never call it blindly.
local function env(name)
  local ok, value = pcall(function() return os and os.getenv and os.getenv(name) end)
  if ok then return value end
  return nil
end

local function standardPath(name)
  local ok, value = pcall(LrPathUtils.getStandardFilePath, name)
  if ok then return value end
  return nil
end

local function configCandidates()
  local list = {}
  local function add(base, ...)
    if not base or base == "" then return end
    local path = base
    for _, part in ipairs({ ... }) do path = LrPathUtils.child(path, part) end
    list[#list + 1] = path
  end
  -- Windows: %APPDATA%\LRFrameFlow, macOS: ~/Library/Application Support/LRFrameFlow
  add(env("LRFF_BRIDGE_DATA_DIR"), CONFIG_FILE)
  add(standardPath("appData"), CONFIG_DIR, CONFIG_FILE)
  add(env("APPDATA"), CONFIG_DIR, CONFIG_FILE)
  local home = standardPath("home")
  add(home, "AppData", "Roaming", CONFIG_DIR, CONFIG_FILE)                  -- Windows
  add(home, "Library", "Application Support", CONFIG_DIR, CONFIG_FILE)      -- macOS
  return list
end

function BridgeClient.loadConfig()
  for _, path in ipairs(configCandidates()) do
    if LrFileUtils.exists(path) == "file" then
      local ok, cfg = pcall(Json.decode, LrFileUtils.readFile(path))
      if ok and type(cfg) == "table" and cfg.port and cfg.token then
        return cfg, nil, path
      end
      return nil, LOC("$$$/LRFrameFlow/Bridge/ConfigDamaged=The Bridge settings file is damaged: ^1", path)
    end
  end
  return nil, LOC "$$$/LRFrameFlow/Bridge/NoConfig=No Bridge settings found. Start the LR-FrameFlow Bridge app once, then try again."
end

local function request(method, path, body)
  local cfg, err = BridgeClient.loadConfig()
  if not cfg then return nil, err end

  local url = string.format("http://127.0.0.1:%d%s", cfg.port, path)
  local headers = {
    { field = "X-LRFF-Token", value = cfg.token },
    { field = "Content-Type", value = "application/json" },
  }
  local raw, response
  if method == "GET" then
    raw, response = LrHttp.get(url, headers, 15)
  else
    raw, response = LrHttp.post(url, Json.encode(body), headers, "POST", 30)
  end

  local status = response and response.status
  if not raw or not status then
    Log.warn("bridge unreachable: %s %s", method, path)
    return nil, NOT_RUNNING
  end

  if status == 204 then return BridgeClient.NO_CONTENT end
  local ok, data = pcall(Json.decode, raw)
  if status >= 200 and status < 300 then
    if not ok then return nil, LOC "$$$/LRFrameFlow/Bridge/Unreadable=The Bridge sent an unreadable answer." end
    return data
  end
  local message = ok and type(data) == "table" and data.error or raw
  Log.warn("bridge %s %s -> %s: %s", method, path, tostring(status), tostring(message))
  if status == 401 then
    return nil, LOC "$$$/LRFrameFlow/Bridge/TokenMismatch=The Bridge rejected the plugin (token mismatch). Restart Lightroom and the Bridge."
  end
  return nil, LOC("$$$/LRFrameFlow/Bridge/Error=Bridge error ^1: ^2", tostring(status), tostring(message))
end

function BridgeClient.health()
  return request("GET", "/health")
end

function BridgeClient.registerPhoto(body)
  return request("POST", "/v1/photos", body)
end

function BridgeClient.photo(uuid)
  return request("GET", "/v1/photos/" .. uuid)
end

function BridgeClient.queueTrain(body)
  return request("POST", "/v1/jobs/train", body)
end

function BridgeClient.queueEdit(body)
  return request("POST", "/v1/jobs/edit", body)
end

function BridgeClient.job(jobId)
  return request("GET", "/v1/jobs/" .. jobId)
end

function BridgeClient.profiles()
  return request("GET", "/v1/profiles")
end

function BridgeClient.automationNext()
  return request("GET", "/v1/automation/next")
end

function BridgeClient.automationResult(id, ok, result)
  return request("POST", "/v1/automation/commands/" .. tostring(id) .. "/result", { ok = ok, result = result })
end

return BridgeClient
