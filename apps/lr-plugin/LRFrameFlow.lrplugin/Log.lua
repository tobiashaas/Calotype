--[[ Plugin log: LRFrameFlow.log in Lightroom's log folder
(Windows: Documents\LrClassicLogs, macOS: ~/Documents/LrClassicLogs). ]]

local LrLogger = import "LrLogger"

local logger = LrLogger("LRFrameFlow")
logger:enable("logfile")

local Log = {}

function Log.info(fmt, ...)
  logger:info(string.format(fmt, ...))
end

function Log.warn(fmt, ...)
  logger:warn(string.format(fmt, ...))
end

return Log
