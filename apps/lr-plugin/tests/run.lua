--[[ Plugin tests without Lightroom: Lightroom's SDK modules are replaced by fakes.

Run from the repository root (Lua 5.1 / LuaJIT, like Lightroom):

    luajit apps/lr-plugin/tests/run.lua
]]

local PLUGIN = "apps/lr-plugin/LRFrameFlow.lrplugin/"
package.path = PLUGIN .. "?.lua;" .. package.path

-- ------------------------------------------------------------ Lightroom fakes

local fake = { files = {}, requests = {}, responses = {}, logs = {} }

local sdk = {
  LrPathUtils = {
    getStandardFilePath = function(name)
      return ({ appData = "C:/Users/test/AppData/Roaming", home = "C:/Users/test" })[name]
    end,
    child = function(base, part) return base .. "/" .. part end,
  },
  LrFileUtils = {
    exists = function(path) return fake.files[path] and "file" or false end,
    readFile = function(path) return fake.files[path] end,
  },
  LrHttp = {
    get = function(url, headers)
      fake.requests[#fake.requests + 1] = { method = "GET", url = url, headers = headers }
      return table.remove(fake.responses, 1)()
    end,
    post = function(url, body, headers, method)
      fake.requests[#fake.requests + 1] = { method = method, url = url, headers = headers, body = body }
      return table.remove(fake.responses, 1)()
    end,
  },
  LrLogger = function()
    return {
      enable = function() end,
      info = function(_, msg) fake.logs[#fake.logs + 1] = msg end,
      warn = function(_, msg) fake.logs[#fake.logs + 1] = msg end,
    }
  end,
  LrTasks = { sleep = function() end, pcall = pcall },
  LrApplication = { versionString = function() return "15.0 (test)" end },
  LrProgressScope = function()
    return { setCaption = function() end, setPortionComplete = function() end,
             setIndeterminate = function() end, isCanceled = function() return false end,
             done = function() end }
  end,
}

-- Lightroom's LOC: "$$$/Key=English default" with ^1..^9 placeholders and ^n line breaks.
function LOC(text, ...) -- luacheck: ignore (global, as in Lightroom)
  local args = { ... }
  local default = text:gsub("^%$%$%$/[^=]*=", "")
  default = default:gsub("%^n", "\n")
  return (default:gsub("%^(%d)", function(i) return tostring(args[tonumber(i)]) end))
end

function import(name) -- luacheck: ignore (global, as in Lightroom)
  return assert(sdk[name], "no fake for " .. name)
end

-- Like Lightroom's sandbox: no os.getenv. (Found in the first real Lightroom test.)
os.getenv = nil
sdk.LrDialogs = { message = function() end }

-- Like Lightroom: reading an undefined global is an error (found when the automation
-- channel silently failed to start). Writing new globals stays allowed.
local function strictGlobals()
  setmetatable(_G, { __index = function(_, name) error("undefined global " .. tostring(name), 2) end })
end

local Json = require "Json"
local BridgeClient = require "BridgeClient"
local PhotoData = require "PhotoData"
local JobWait = require "JobWait"

local CONFIG_PATH = "C:/Users/test/AppData/Roaming/LRFrameFlow/bridge.json"

local function respond(status, body)
  fake.responses[#fake.responses + 1] = function()
    return type(body) == "string" and body or Json.encode(body), { status = status }
  end
end

local function unreachable()
  fake.responses[#fake.responses + 1] = function() return nil, { error = { name = "connection refused" } } end
end

local function header(req, field)
  for _, h in ipairs(req.headers) do
    if h.field == field then return h.value end
  end
end

-- ------------------------------------------------------------ tiny harness

local passed, failed = 0, 0
local function test(name, fn)
  fake.files, fake.requests, fake.responses, fake.logs = {}, {}, {}, {}
  local ok, err = pcall(fn)
  if ok then
    passed = passed + 1
    print("ok   " .. name)
  else
    failed = failed + 1
    print("FAIL " .. name .. "\n     " .. tostring(err))
  end
end

local function eq(actual, expected, what)
  if actual ~= expected then
    error(string.format("%s: expected %s, got %s", what or "value", tostring(expected), tostring(actual)), 2)
  end
end

-- ------------------------------------------------------------ Json

test("json roundtrip of develop-settings-like data", function()
  local value = {
    Exposure2012 = 0.35, Temperature = 5600, Tint = -8, ProcessVersion = "15.4",
    AutoLateralCA = true, ToneCurvePV2012 = { 0, 0, 255, 255 },
    Look = Json.object({}), Name = 'Quote " and \\ backslash\nnewline',
  }
  local back = Json.decode(Json.encode(value))
  eq(back.Exposure2012, 0.35, "float")
  eq(back.Temperature, 5600, "integer")
  eq(back.Tint, -8, "negative")
  eq(back.ProcessVersion, "15.4", "string")
  eq(back.AutoLateralCA, true, "bool")
  eq(#back.ToneCurvePV2012, 4, "array length")
  eq(back.ToneCurvePV2012[3], 255, "array item")
  eq(Json.encode(back.Look), "{}", "empty object stays object")
  eq(back.Name, value.Name, "escapes")
end)

test("json encodes integers without decimals and arrays as arrays", function()
  eq(Json.encode({ 1, 2, 3 }), "[1,2,3]")
  eq(Json.encode({ a = 1, b = { 2.5 } }), '{"a":1,"b":[2.5]}')
  eq(Json.encode({}), "[]")
  eq(Json.encode(0 / 0), "null")
end)

test("json decodes unicode escapes, null and nesting", function()
  local v = Json.decode('{"t":"Gr\\u00fc\\u00dfe \\ud83d\\udcf7","n":null,"a":[{"x":-1.5e2}]}')
  eq(v.t, "Grüße 📷", "unicode")
  eq(v.n, Json.null, "null")
  eq(v.a[1].x, -150, "exponent")
end)

test("json rejects broken input", function()
  for _, bad in ipairs({ "{", '{"a":}', "[1,]", "tru", '{"a":1} x' }) do
    local ok = pcall(Json.decode, bad)
    eq(ok, false, "decode " .. bad)
  end
end)

-- ------------------------------------------------------------ BridgeClient

test("bridge config is found via the home folder when appData is not the roaming folder", function()
  local original = sdk.LrPathUtils.getStandardFilePath
  sdk.LrPathUtils.getStandardFilePath = function(name)
    return ({ appData = "C:/Users/test/AppData/Roaming/Adobe/Lightroom", home = "C:/Users/test" })[name]
  end
  fake.files[CONFIG_PATH] = Json.encode({ port = 47600, token = "t" })
  local cfg, err = BridgeClient.loadConfig()
  sdk.LrPathUtils.getStandardFilePath = original
  eq(err, nil, "error")
  eq(cfg.port, 47600, "port")
end)

test("bridge client sends token and reads JSON", function()
  fake.files[CONFIG_PATH] = Json.encode({ port = 47600, token = "secret", api_base_url = "http://srv" })
  respond(200, { status = "ok", version = "0.1.0" })
  local health, err = BridgeClient.health()
  eq(err, nil, "error")
  eq(health.version, "0.1.0", "version")
  eq(fake.requests[1].url, "http://127.0.0.1:47600/health", "url")
  eq(header(fake.requests[1], "X-LRFF-Token"), "secret", "token header")
end)

test("bridge client explains missing config, bridge down, rejected token, errors", function()
  local _, err = BridgeClient.health()
  assert(err:find("Start the LR%-FrameFlow Bridge app once"), err)

  fake.files[CONFIG_PATH] = Json.encode({ port = 47600, token = "secret" })
  unreachable()
  _, err = BridgeClient.health()
  assert(err:find("not running"), err)

  respond(401, { error = "missing or wrong X-LRFF-Token" })
  _, err = BridgeClient.profiles()
  assert(err:find("token mismatch"), err)

  respond(422, { error = "register these photos first" })
  _, err = BridgeClient.queueEdit({})
  assert(err:find("422") and err:find("register these photos first"), err)
end)

test("bridge client posts JSON bodies", function()
  fake.files[CONFIG_PATH] = Json.encode({ port = 1234, token = "t" })
  respond(202, { job_id = "j1", status = "waiting_for_photos" })
  local job = BridgeClient.queueTrain({ schema_version = "bridge-train-v1", lr_catalog_uuids = { "a" } })
  eq(job.job_id, "j1", "job id")
  local req = fake.requests[1]
  eq(req.method, "POST", "method")
  eq(req.url, "http://127.0.0.1:1234/v1/jobs/train", "url")
  eq(Json.decode(req.body).lr_catalog_uuids[1], "a", "body")
end)

-- ------------------------------------------------------------ PhotoData

local function fakePhoto(uuid, fileFormat, settings)
  local raw = {
    uuid = uuid, fileFormat = fileFormat, path = "D:/Shoot/" .. uuid .. ".CR3",
    isoSpeedRating = 400, aperture = 2.8, focalLength = 85,
    rating = 4, pickStatus = -1, colorNameForLabel = "none",
  }
  return {
    getRawMetadata = function(_, key) return raw[key] end,
    getFormattedMetadata = function(_, key) return ({ cameraModel = "Canon EOS R5" })[key] end,
    getDevelopSettings = function() return settings or { Exposure2012 = 0.5, Temperature = 5200 } end,
    applied = nil,
    applyDevelopSettings = function(self, s) self.applied = s end,
  }
end

test("photo data maps file types and builds the bridge request", function()
  eq(PhotoData.formatType("RAW"), "raw")
  eq(PhotoData.formatType("DNG"), "raw")
  eq(PhotoData.formatType("JPG"), "jpeg_tiff")
  eq(PhotoData.formatType("VIDEO"), nil)

  local body, formatType = PhotoData.collect(fakePhoto("u1", "RAW"))
  eq(formatType, "raw", "format")
  eq(body.schema_version, "bridge-photo-v1", "schema")
  eq(body.file_path, "D:/Shoot/u1.CR3", "path")
  local json = Json.decode(Json.encode(body))
  eq(json.lr_develop_settings.Temperature, 5200, "settings")
  eq(json.exif_snapshot.camera, "Canon EOS R5", "exif")
  eq(json.lr_metadata.rating, 4, "rating")
  eq(json.lr_metadata.pick_status, -1, "rejected flag")
  eq(json.lr_metadata.color_label, nil, "label 'none' dropped")

  local none, reason = PhotoData.collect(fakePhoto("v1", "VIDEO"))
  eq(none, nil, "video skipped")
  assert(reason:find("VIDEO"), reason)

  local empty = Json.encode(PhotoData.collect(fakePhoto("u2", "JPG", {})))
  assert(empty:find('"lr_develop_settings":{}', 1, true), "empty settings stay an object: " .. empty)
end)

test("prepared settings switch white balance to custom", function()
  local s = PhotoData.prepareSettings({ Temperature = 5600, Exposure2012 = 0.2, Bogus = Json.null })
  eq(s.WhiteBalance, "Custom", "white balance")
  eq(s.Bogus, nil, "null dropped")
  eq(PhotoData.prepareSettings({ Exposure2012 = 0.2 }).WhiteBalance, nil, "untouched without WB")
  eq(PhotoData.prepareSettings({ ConvertToGrayscale = "True" }).ConvertToGrayscale, true, "XMP boolean")
end)

-- ------------------------------------------------------------ JobWait

local function fakeProgress(cancelAfter)
  local p = { captions = {}, calls = 0 }
  function p:isCanceled()
    self.calls = self.calls + 1
    return cancelAfter ~= nil and self.calls > cancelAfter
  end
  function p:setCaption(c) self.captions[#self.captions + 1] = c end
  function p:setPortionComplete() end
  function p:setIndeterminate() end
  return p
end

test("register photos skips videos and collects formats", function()
  fake.files[CONFIG_PATH] = Json.encode({ port = 1, token = "t" })
  respond(202, { status = "pending" })
  respond(202, { status = "pending" })
  local photos = { fakePhoto("a", "RAW"), fakePhoto("v", "VIDEO"), fakePhoto("b", "DNG") }
  local reg = JobWait.registerPhotos(photos, fakeProgress())
  eq(#reg.uuids, 2, "registered")
  eq(#reg.skipped, 1, "skipped")
  eq(reg.formats.raw, true, "raw")
  eq(reg.photosByUuid.b, photos[3], "lookup")
end)

test("wait for job polls until completed and survives a bridge hiccup", function()
  fake.files[CONFIG_PATH] = Json.encode({ port = 1, token = "t" })
  respond(200, { job_id = "j", status = "waiting_for_photos" })
  unreachable()
  respond(200, { job_id = "j", status = "running" })
  respond(200, { job_id = "j", status = "completed", results = { { lr_catalog_uuid = "a", lr_settings = { Exposure2012 = 0.3 } } } })
  local progress = fakeProgress()
  local job = JobWait.waitForJob("j", progress, "Editing")
  eq(job.status, "completed", "status")
  eq(job.results[1].lr_settings.Exposure2012, 0.3, "result")
  assert(progress.captions[#progress.captions]:find("Working on the server"), progress.captions[#progress.captions])
end)

test("wait for job stops on cancel", function()
  fake.files[CONFIG_PATH] = Json.encode({ port = 1, token = "t" })
  respond(200, { job_id = "j", status = "queued" })
  local job, err = JobWait.waitForJob("j", fakeProgress(1), "Training")
  eq(job, nil, "no job")
  eq(err, "canceled", "reason")
end)

-- ------------------------------------------------------------ translations

local function readFile(path)
  local f = assert(io.open(path, "rb"))
  local text = f:read("*a")
  f:close()
  return text
end

local function placeholders(text)
  local found = {}
  for d in text:gmatch("%^(%d)") do found[#found + 1] = d end
  table.sort(found)
  return table.concat(found, ",")
end

test("every UI text has a German translation with the same placeholders", function()
  local english = {}
  for _, file in ipairs({ "Info.lua", "BridgeClient.lua", "JobWait.lua", "Actions.lua", "TrainProfile.lua",
                          "ApplyProfile.lua", "BridgeStatus.lua", "AutomationCommands.lua" }) do
    local src = readFile(PLUGIN .. file)
    for key, value in src:gmatch('"(%$%$%$/LRFrameFlow/[%w/]+)=(.-[^\\])"') do english[key] = value end
  end
  local german = {}
  for key, value in readFile(PLUGIN .. "TranslatedStrings_de.txt"):gmatch('"(%$%$%$/LRFrameFlow/[%w/]+)=([^\n]-)"%s*\n') do
    german[key] = value
  end
  local count = 0
  for key, value in pairs(english) do
    count = count + 1
    assert(german[key], "missing German text for " .. key)
    eq(placeholders(german[key]), placeholders(value), "placeholders of " .. key)
  end
  for key in pairs(german) do assert(english[key], "German text without code: " .. key) end
  assert(count > 70, "found only " .. count .. " UI texts")
  eq(german["$$$/LRFrameFlow/Language"], "de", "language marker")
end)

-- ------------------------------------------------------------ automation commands

local function fakeCatalog(photos)
  local byUuid = {}
  for _, p in ipairs(photos) do byUuid[p:getRawMetadata("uuid")] = p end
  return {
    getPath = function() return "C:/test.lrcat" end,
    getAllPhotos = function() return photos end,
    findPhotoByUuid = function(_, uuid) return byUuid[uuid] end,
    batchGetRawMetadata = function(_, list, keys)
      local out = {}
      for _, p in ipairs(list) do
        local m = {}
        for _, k in ipairs(keys) do m[k] = p:getRawMetadata(k) end
        out[p] = m
      end
      return out
    end,
    withWriteAccessDo = function(_, _, fn) fn() end,
    setSelectedPhotos = function() end,
  }
end

test("automation: ping, list, read and restore develop settings", function()
  local Commands = require "AutomationCommands"
  local photos = { fakePhoto("a", "RAW"), fakePhoto("v", "VIDEO"), fakePhoto("b", "JPG") }
  local catalog = fakeCatalog(photos)
  local ok, ping = Commands.run(catalog, { command = "ping", args = {} })
  eq(ok, true, "ping ok")
  eq(ping.photos, 3, "photo count")
  eq(ping.language, "en", "language marker")
  local _, list = Commands.run(catalog, { command = "list_photos", args = { format = "raw" } })
  eq(#list.photos, 1, "format filter")
  eq(list.photos[1].uuid, "a", "uuid")
  local _, dev = Commands.run(catalog, { command = "develop_settings", args = { uuids = { "a", "x" }, keys = { "Temperature" } } })
  eq(dev.settings.a.Temperature, 5200, "read settings")
  eq(dev.missing[1], "x", "missing uuid reported")
  local _, set = Commands.run(catalog, { command = "set_develop_settings", args = { settings = { a = { Exposure2012 = 0.7 } } } })
  eq(set.updated, 1, "restored")
  eq(photos[1].applied.Exposure2012, 0.7, "applied to photo")
end)

test("automation: refuses unknown commands and reports errors instead of crashing", function()
  local Commands = require "AutomationCommands"
  local catalog = fakeCatalog({})
  local ok, r = Commands.run(catalog, { command = "run", args = {} })
  eq(ok, false, "run is not a command")
  assert(r.error:find("unknown"), r.error)
  ok, r = Commands.run(catalog, { command = "os.execute", args = {} })
  eq(ok, false, "unknown command")
  fake.files[CONFIG_PATH] = Json.encode({ port = 1, token = "t" })
  unreachable()
  ok, r = Commands.run(catalog, { command = "apply", args = { profile = "X", uuids = {} } })
  eq(ok, false, "bridge down is an error result")
  assert(r.error:find("not running"), r.error)
end)

test("automation: apply runs the same flow as the menu and writes the results", function()
  local Commands = require "AutomationCommands"
  fake.files[CONFIG_PATH] = Json.encode({ port = 1, token = "t" })
  local photos = { fakePhoto("a", "RAW"), fakePhoto("b", "RAW") }
  local catalog = fakeCatalog(photos)
  respond(200, { { profile_id = "p1", name = "Test", genre = "event", format_type = "raw", status = "ready", version = 1 } })
  respond(202, { status = "pending" })  -- register a
  respond(202, { status = "pending" })  -- register b
  respond(202, { job_id = "j1", status = "waiting_for_photos" })
  respond(200, { job_id = "j1", status = "completed", results = {
    { lr_catalog_uuid = "a", lr_settings = { Exposure2012 = 0.3, Temperature = 5600 } },
    { lr_catalog_uuid = "b", lr_settings = { Exposure2012 = -0.2 } },
  } })
  local ok, r = Commands.run(catalog, { command = "apply", args = { profile = "Test", uuids = { "a", "b" } } })
  eq(ok, true, "apply ok: " .. tostring(r.error))
  eq(r.applied, 2, "applied")
  eq(photos[1].applied.Temperature, 5600, "settings written")
  eq(photos[1].applied.WhiteBalance, "Custom", "white balance custom")
  eq(Json.decode(fake.requests[4].body).profile_id, "p1", "edit job for the chosen profile")
end)

-- ------------------------------------------------------------ syntax of UI scripts

test("automation init runs under Lightroom's strict globals", function()
  fake.files[CONFIG_PATH] = Json.encode({ port = 1, token = "t", automation = false })
  local started
  sdk.LrTasks.startAsyncTask = function(fn) started = true; fn() end
  strictGlobals()
  local ok, err = pcall(assert(loadfile(PLUGIN .. "Automation.lua")))
  setmetatable(_G, nil)
  eq(ok, true, "init: " .. tostring(err))
  eq(started, true, "task started")
  eq(rawget(_G, "LRFF_AUTOMATION_GENERATION") >= 1, true, "generation set")
end)

test("menu scripts compile", function()
  for _, file in ipairs({ "Info.lua", "TrainProfile.lua", "ApplyProfile.lua", "BridgeStatus.lua",
                          "Actions.lua", "Automation.lua", "AutomationCommands.lua" }) do
    assert(loadfile(PLUGIN .. file))
  end
  local info = assert(loadfile(PLUGIN .. "Info.lua"))()
  eq(info.LrToolkitIdentifier, "io.github.lrframeflow", "toolkit id")
  for _, item in ipairs(info.LrLibraryMenuItems) do
    assert(io.open(PLUGIN .. item.file), "menu file exists: " .. item.file)
  end
end)

print(string.format("\n%d passed, %d failed", passed, failed))
os.exit(failed == 0 and 0 or 1)
