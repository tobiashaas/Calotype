--[[ Minimal JSON encode/decode for Lua 5.1 (Lightroom ships no JSON library).

Json.encode(value)  -> string. Tables with keys 1..n are arrays, all others objects.
                       Json.object() marks an empty table as {} instead of [].
Json.decode(string) -> value. JSON null becomes Json.null (so object keys survive).
]]

local Json = {}

Json.null = setmetatable({}, { __tostring = function() return "null" end })
local OBJECT_MARK = {}

function Json.object(t)
  return setmetatable(t or {}, OBJECT_MARK)
end

-- ---------------------------------------------------------------- encode

local escapes = {
  ['"'] = '\\"', ["\\"] = "\\\\", ["\b"] = "\\b", ["\f"] = "\\f",
  ["\n"] = "\\n", ["\r"] = "\\r", ["\t"] = "\\t",
}

local function encodeString(s)
  return '"' .. s:gsub('[%c"\\]', function(c)
    return escapes[c] or string.format("\\u%04x", c:byte())
  end) .. '"'
end

local function isArray(t)
  if getmetatable(t) == OBJECT_MARK then return false end
  local n = 0
  for _ in pairs(t) do n = n + 1 end
  if n == 0 then return true end
  for i = 1, n do
    if t[i] == nil then return false end
  end
  return true
end

local encodeValue

local function encodeTable(t, seen)
  if seen[t] then error("Json.encode: cyclic table") end
  seen[t] = true
  local parts = {}
  if isArray(t) then
    for i = 1, #t do parts[i] = encodeValue(t[i], seen) end
    seen[t] = nil
    return "[" .. table.concat(parts, ",") .. "]"
  end
  local keys = {}
  for k in pairs(t) do keys[#keys + 1] = tostring(k) end
  table.sort(keys) -- stable output, easier to debug and test
  for _, k in ipairs(keys) do
    local v = t[k]
    if v == nil then v = t[tonumber(k)] end
    parts[#parts + 1] = encodeString(k) .. ":" .. encodeValue(v, seen)
  end
  seen[t] = nil
  return "{" .. table.concat(parts, ",") .. "}"
end

encodeValue = function(v, seen)
  local kind = type(v)
  if v == nil or v == Json.null then
    return "null"
  elseif kind == "boolean" then
    return v and "true" or "false"
  elseif kind == "number" then
    if v ~= v or v == math.huge or v == -math.huge then return "null" end
    if v == math.floor(v) and math.abs(v) < 1e15 then
      return string.format("%d", v)
    end
    return string.format("%.14g", v)
  elseif kind == "string" then
    return encodeString(v)
  elseif kind == "table" then
    return encodeTable(v, seen)
  end
  error("Json.encode: cannot encode " .. kind)
end

function Json.encode(v)
  return encodeValue(v, {})
end

-- ---------------------------------------------------------------- decode

local function decodeError(s, i, msg)
  error(string.format("Json.decode: %s at position %d near %q", msg, i, s:sub(i, i + 10)))
end

local function skip(s, i)
  return s:find("[^ \t\r\n]", i) or #s + 1
end

local function utf8char(cp)
  if cp < 0x80 then return string.char(cp) end
  if cp < 0x800 then
    return string.char(0xC0 + math.floor(cp / 0x40), 0x80 + cp % 0x40)
  end
  if cp < 0x10000 then
    return string.char(0xE0 + math.floor(cp / 0x1000), 0x80 + math.floor(cp / 0x40) % 0x40,
      0x80 + cp % 0x40)
  end
  return string.char(0xF0 + math.floor(cp / 0x40000), 0x80 + math.floor(cp / 0x1000) % 0x40,
    0x80 + math.floor(cp / 0x40) % 0x40, 0x80 + cp % 0x40)
end

local decodeValue

local function decodeString(s, i)
  local out, j = {}, i + 1
  while true do
    local c = s:sub(j, j)
    if c == "" then decodeError(s, i, "unterminated string") end
    if c == '"' then return table.concat(out), j + 1 end
    if c == "\\" then
      local e = s:sub(j + 1, j + 1)
      local simple = { b = "\b", f = "\f", n = "\n", r = "\r", t = "\t", ['"'] = '"', ["\\"] = "\\", ["/"] = "/" }
      if simple[e] then
        out[#out + 1] = simple[e]
        j = j + 2
      elseif e == "u" then
        local cp = tonumber(s:sub(j + 2, j + 5), 16)
        if not cp then decodeError(s, j, "bad \\u escape") end
        j = j + 6
        if cp >= 0xD800 and cp <= 0xDBFF and s:sub(j, j + 1) == "\\u" then
          local low = tonumber(s:sub(j + 2, j + 5), 16)
          if low and low >= 0xDC00 and low <= 0xDFFF then
            cp = 0x10000 + (cp - 0xD800) * 0x400 + (low - 0xDC00)
            j = j + 6
          end
        end
        out[#out + 1] = utf8char(cp)
      else
        decodeError(s, j, "bad escape")
      end
    else
      local stop = s:find('["\\]', j) or #s + 1
      out[#out + 1] = s:sub(j, stop - 1)
      j = stop
    end
  end
end

local function decodeArray(s, i)
  local arr, n = {}, 0
  i = skip(s, i + 1)
  if s:sub(i, i) == "]" then return arr, i + 1 end
  while true do
    local v
    v, i = decodeValue(s, i)
    n = n + 1
    arr[n] = v
    i = skip(s, i)
    local c = s:sub(i, i)
    if c == "]" then return arr, i + 1 end
    if c ~= "," then decodeError(s, i, "expected ',' or ']'") end
    i = skip(s, i + 1)
  end
end

local function decodeObject(s, i)
  local obj = Json.object({})
  i = skip(s, i + 1)
  if s:sub(i, i) == "}" then return obj, i + 1 end
  while true do
    if s:sub(i, i) ~= '"' then decodeError(s, i, "expected key") end
    local k
    k, i = decodeString(s, i)
    i = skip(s, i)
    if s:sub(i, i) ~= ":" then decodeError(s, i, "expected ':'") end
    local v
    v, i = decodeValue(s, skip(s, i + 1))
    obj[k] = v
    i = skip(s, i)
    local c = s:sub(i, i)
    if c == "}" then return obj, i + 1 end
    if c ~= "," then decodeError(s, i, "expected ',' or '}'") end
    i = skip(s, i + 1)
  end
end

decodeValue = function(s, i)
  i = skip(s, i)
  local c = s:sub(i, i)
  if c == "{" then return decodeObject(s, i) end
  if c == "[" then return decodeArray(s, i) end
  if c == '"' then return decodeString(s, i) end
  if s:sub(i, i + 3) == "true" then return true, i + 4 end
  if s:sub(i, i + 4) == "false" then return false, i + 5 end
  if s:sub(i, i + 3) == "null" then return Json.null, i + 4 end
  local num = s:match("^-?%d+%.?%d*[eE]?[-+]?%d*", i)
  if num and num ~= "" and num ~= "-" then
    local v = tonumber(num)
    if v then return v, i + #num end
  end
  decodeError(s, i, "unexpected character")
end

function Json.decode(s)
  if type(s) ~= "string" then error("Json.decode: expected string") end
  local v, i = decodeValue(s, 1)
  i = skip(s, i)
  if i <= #s then decodeError(s, i, "trailing data") end
  return v
end

return Json
