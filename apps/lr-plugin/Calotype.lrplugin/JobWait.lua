--[[ Register photos with the Bridge and wait for a job, with progress and cancel. ]]

local LrTasks = import "LrTasks"

local BridgeClient = require "BridgeClient"
local PhotoData = require "PhotoData"

local JobWait = {}

local STATUS_TEXT = {
  waiting_for_photos = LOC "$$$/Calotype/Job/Uploading=Preparing and uploading photos",
  queued = LOC "$$$/Calotype/Job/Queued=Waiting for the server",
  running = LOC "$$$/Calotype/Job/Running=Working on the server",
}

local POLL_SECONDS = 2
local MAX_BRIDGE_FAILURES = 30 -- about one minute without Bridge

--- Register photos. Returns { uuids, photosByUuid, formats, skipped } or nil, error.
function JobWait.registerPhotos(photos, progress)
  local result = { uuids = {}, photosByUuid = {}, formats = {}, skipped = {} }
  for i, photo in ipairs(photos) do
    if progress:isCanceled() then return nil, "canceled" end
    progress:setCaption(LOC("$$$/Calotype/Job/Handing=Handing photo ^1 of ^2 to the Bridge", i, #photos))
    progress:setPortionComplete(i - 1, #photos)
    local body, formatType = PhotoData.collect(photo)
    if not body then
      local reason = formatType -- collect() returns nil, reason for unusable photos
      result.skipped[#result.skipped + 1] = reason
    else
      local _, err = BridgeClient.registerPhoto(body)
      if err then return nil, err end
      result.uuids[#result.uuids + 1] = body.lr_catalog_uuid
      result.photosByUuid[body.lr_catalog_uuid] = photo
      result.formats[formatType] = true
    end
  end
  progress:setPortionComplete(1, 1)
  return result
end

--- Poll until the job is completed or failed. Returns the job state, or nil, error.
-- If the user cancels, returns nil, "canceled" — the job keeps running in the Bridge.
function JobWait.waitForJob(jobId, progress, label)
  progress:setIndeterminate()
  local failures = 0
  while true do
    if progress:isCanceled() then return nil, "canceled" end
    local job, err = BridgeClient.job(jobId)
    if job then
      failures = 0
      if job.status == "completed" or job.status == "failed" then return job end
      progress:setCaption(LOC("$$$/Calotype/Job/Status=^1: ^2 ...", label, STATUS_TEXT[job.status] or job.status))
    else
      failures = failures + 1
      if failures >= MAX_BRIDGE_FAILURES then return nil, err end
      progress:setCaption(LOC("$$$/Calotype/Job/WaitingBridge=^1: waiting for the Bridge ...", label))
    end
    LrTasks.sleep(POLL_SECONDS)
  end
end

return JobWait
