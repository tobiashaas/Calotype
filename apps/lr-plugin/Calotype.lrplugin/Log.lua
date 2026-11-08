--[[ Plugin log: Calotype.log in Lightroom's log folder
(Windows: %LOCALAPPDATA%\Adobe\Lightroom\Logs\LrClassicLogs, macOS: ~/Library/Logs/Adobe/Lightroom/LrClassicLogs). ]]

local LrLogger = import "LrLogger"

local logger = LrLogger("Calotype")
logger:enable("logfile")

local Log = {}

function Log.info(fmt, ...)
  logger:info(string.format(fmt, ...))
end

function Log.warn(fmt, ...)
  logger:warn(string.format(fmt, ...))
end

return Log
