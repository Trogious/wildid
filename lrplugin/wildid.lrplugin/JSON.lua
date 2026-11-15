--[[
JSON encode/decode for the WildID plugin. Lua 5.1 (Lightroom's runtime), no dependencies.

Scope: exactly what talking to `wildid serve` needs.
- decode: objects, arrays, strings (incl. \uXXXX and surrogate pairs -> UTF-8 bytes),
  numbers, true/false/null. null becomes nil (the field is simply absent).
- encode: nil/boolean/number/string/table. A table encodes as an array when it is a
  sequence (length > 0) or was marked with JSON.array(); {} encodes as an object.
]]

local JSON = {}

-- ---------------------------------------------------------------- encode

local ESCAPES = {
    ['"'] = '\\"', ['\\'] = '\\\\', ['\b'] = '\\b', ['\f'] = '\\f',
    ['\n'] = '\\n', ['\r'] = '\\r', ['\t'] = '\\t',
}

local ARRAY_MT = { __wildid_json_array = true }

function JSON.array(t)
    return setmetatable(t or {}, ARRAY_MT)
end

local function isArray(t)
    local mt = getmetatable(t)
    if mt and mt.__wildid_json_array then return true end
    return rawget(t, 1) ~= nil and #t > 0
end

local function encodeString(s)
    local out = s:gsub('[%z\1-\31\\"]', function(c)
        return ESCAPES[c] or string.format('\\u%04x', c:byte())
    end)
    return '"' .. out .. '"'
end

local function encodeValue(v, depth)
    depth = depth or 0
    if depth > 32 then error('JSON encode: nesting too deep') end
    local tv = type(v)
    if v == nil then
        return 'null'
    elseif tv == 'boolean' then
        return v and 'true' or 'false'
    elseif tv == 'number' then
        if v ~= v or v == math.huge or v == -math.huge then
            error('JSON encode: cannot encode NaN/Inf')
        end
        if v == math.floor(v) and math.abs(v) < 1e15 then
            return string.format('%d', v)
        end
        return string.format('%.14g', v)
    elseif tv == 'string' then
        return encodeString(v)
    elseif tv == 'table' then
        local parts = {}
        if isArray(v) then
            for i = 1, #v do
                parts[#parts + 1] = encodeValue(v[i], depth + 1)
            end
            return '[' .. table.concat(parts, ',') .. ']'
        end
        for k, val in pairs(v) do
            if type(k) ~= 'string' then error('JSON encode: object keys must be strings') end
            parts[#parts + 1] = encodeString(k) .. ':' .. encodeValue(val, depth + 1)
        end
        return '{' .. table.concat(parts, ',') .. '}'
    end
    error('JSON encode: unsupported type ' .. tv)
end

function JSON.encode(v)
    return encodeValue(v, 0)
end

-- ---------------------------------------------------------------- decode

local function utf8Char(code)
    -- code point -> UTF-8 bytes (Lua 5.1 has no utf8 library)
    if code < 0x80 then
        return string.char(code)
    elseif code < 0x800 then
        return string.char(0xC0 + math.floor(code / 0x40), 0x80 + code % 0x40)
    elseif code < 0x10000 then
        return string.char(
            0xE0 + math.floor(code / 0x1000),
            0x80 + math.floor(code / 0x40) % 0x40,
            0x80 + code % 0x40)
    else
        return string.char(
            0xF0 + math.floor(code / 0x40000),
            0x80 + math.floor(code / 0x1000) % 0x40,
            0x80 + math.floor(code / 0x40) % 0x40,
            0x80 + code % 0x40)
    end
end

local decodeValue  -- forward declaration

local function decodeError(s, i, msg)
    error(string.format('JSON decode: %s at position %d (near %q)', msg, i, s:sub(i, i + 12)), 0)
end

local function skipWhitespace(s, i)
    local _, j = s:find('^[ \t\r\n]*', i)
    return j + 1
end

local function decodeString(s, i)
    -- i points at the opening quote
    local parts = {}
    local j = i + 1
    while true do
        local c = s:sub(j, j)
        if c == '' then decodeError(s, j, 'unterminated string') end
        if c == '"' then
            return table.concat(parts), j + 1
        elseif c == '\\' then
            local esc = s:sub(j + 1, j + 1)
            if esc == 'u' then
                local hex = s:sub(j + 2, j + 5)
                if not hex:match('^%x%x%x%x$') then decodeError(s, j, 'bad \\u escape') end
                local code = tonumber(hex, 16)
                j = j + 6
                if code >= 0xD800 and code <= 0xDBFF then  -- high surrogate
                    local hex2 = s:sub(j + 2, j + 5)
                    if s:sub(j, j + 1) == '\\u' and hex2:match('^%x%x%x%x$') then
                        local low = tonumber(hex2, 16)
                        if low >= 0xDC00 and low <= 0xDFFF then
                            code = 0x10000 + (code - 0xD800) * 0x400 + (low - 0xDC00)
                            j = j + 6
                        end
                    end
                end
                parts[#parts + 1] = utf8Char(code)
            else
                local map = { ['"'] = '"', ['\\'] = '\\', ['/'] = '/', b = '\b', f = '\f',
                              n = '\n', r = '\r', t = '\t' }
                local real = map[esc]
                if not real then decodeError(s, j, 'bad escape \\' .. esc) end
                parts[#parts + 1] = real
                j = j + 2
            end
        else
            -- consume a run of plain characters at once
            local stop = s:find('["\\]', j) or (#s + 1)
            parts[#parts + 1] = s:sub(j, stop - 1)
            j = stop
        end
    end
end

local function decodeNumber(s, i)
    local numStr = s:match('^-?%d+%.?%d*[eE]?[+%-]?%d*', i)
    if not numStr or numStr == '' then decodeError(s, i, 'bad number') end
    local n = tonumber(numStr)
    if n == nil then decodeError(s, i, 'bad number') end
    return n, i + #numStr
end

local function decodeArray(s, i)
    local arr = JSON.array({})
    local j = skipWhitespace(s, i + 1)
    if s:sub(j, j) == ']' then return arr, j + 1 end
    while true do
        local value
        value, j = decodeValue(s, j)
        arr[#arr + 1] = value
        j = skipWhitespace(s, j)
        local c = s:sub(j, j)
        if c == ']' then return arr, j + 1 end
        if c ~= ',' then decodeError(s, j, "expected ',' or ']'") end
        j = skipWhitespace(s, j + 1)
    end
end

local function decodeObject(s, i)
    local obj = {}
    local j = skipWhitespace(s, i + 1)
    if s:sub(j, j) == '}' then return obj, j + 1 end
    while true do
        if s:sub(j, j) ~= '"' then decodeError(s, j, 'expected object key') end
        local key, value
        key, j = decodeString(s, j)
        j = skipWhitespace(s, j)
        if s:sub(j, j) ~= ':' then decodeError(s, j, "expected ':'") end
        j = skipWhitespace(s, j + 1)
        value, j = decodeValue(s, j)
        obj[key] = value
        j = skipWhitespace(s, j)
        local c = s:sub(j, j)
        if c == '}' then return obj, j + 1 end
        if c ~= ',' then decodeError(s, j, "expected ',' or '}'") end
        j = skipWhitespace(s, j + 1)
    end
end

decodeValue = function(s, i)
    i = skipWhitespace(s, i)
    local c = s:sub(i, i)
    if c == '{' then return decodeObject(s, i) end
    if c == '[' then return decodeArray(s, i) end
    if c == '"' then return decodeString(s, i) end
    if s:sub(i, i + 3) == 'true' then return true, i + 4 end
    if s:sub(i, i + 4) == 'false' then return false, i + 5 end
    if s:sub(i, i + 3) == 'null' then return nil, i + 4 end
    if c == '-' or c:match('%d') then return decodeNumber(s, i) end
    decodeError(s, i, 'unexpected character')
end

--- Returns the decoded value, or nil + an error message.
function JSON.decode(s)
    if type(s) ~= 'string' then return nil, 'JSON decode: not a string' end
    local ok, valueOrErr, after = pcall(decodeValue, s, 1)
    if not ok then return nil, tostring(valueOrErr) end
    local rest = skipWhitespace(s, after)
    if rest <= #s then return nil, 'JSON decode: trailing data at position ' .. rest end
    return valueOrErr
end

return JSON
