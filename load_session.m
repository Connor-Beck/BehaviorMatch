function session = load_session(matfile, varargin)
%LOAD_SESSION  Load a BehaviorMatch .mat session and normalize MATLAB types.
%
%   session = LOAD_SESSION(matfile)
%   session = LOAD_SESSION(matfile, 'datetime', true)   % adds pc_datetime columns
%   session = LOAD_SESSION(matfile, 'minimal', true)    % drops audit-log events
%
%   BehaviorMatch writes .mat files with plain MATLAB structs. This helper
%   turns variable-length event and frame structs into tables and converts
%   low-cardinality strings to categoricals so downstream MATLAB code can use
%   table syntax and categorical comparisons instead of repeated strcmp calls.

MIN_PARSER_VERSION = "0.2.0";
CATEGORICAL_FIELDS = ["cue1", "cue2", "correct_side", "chosen_side", ...
                      "outcome", "trial_type", "kind", "tag", "source", ...
                      "sensor", "mega_tag"];

p = inputParser;
addParameter(p, 'datetime', false, @(x) islogical(x) || isnumeric(x));
addParameter(p, 'minimal', false, @(x) islogical(x) || isnumeric(x));
parse(p, varargin{:});
add_datetime = logical(p.Results.datetime);
minimal = logical(p.Results.minimal);

raw = load(matfile);
if ~isfield(raw, 'session')
    error('load_session:missing_session', ...
        '%s does not contain a top-level session struct.', matfile);
end
session = raw.session;

if isfield(session, 'parser_version')
    parser_version = string(session.parser_version);
    if version_less_than(parser_version, MIN_PARSER_VERSION)
        error('load_session:stale', ...
            'parser_version %s < %s. Re-run BehaviorMatch before loading.', ...
            parser_version, MIN_PARSER_VERSION);
    end
end

if isfield(session, 'events')
    session.events = convert_to_table(session.events, CATEGORICAL_FIELDS, add_datetime);
    if minimal
        session = rmfield(session, 'events');
    end
end

if isfield(session, 'timing')
    timing_fields = fieldnames(session.timing);
    for i = 1:numel(timing_fields)
        name = timing_fields{i};
        if strcmp(name, 'clock_corrections')
            continue
        end
        session.timing.(name) = convert_to_table(session.timing.(name), ...
                                                  CATEGORICAL_FIELDS, add_datetime);
    end
end

if isfield(session, 'trials')
    trials = session.trials;
    for i = 1:numel(trials)
        if isfield(trials(i), 'sensor_events')
            trials(i).sensor_events = convert_to_table(trials(i).sensor_events, ...
                                                        CATEGORICAL_FIELDS, add_datetime);
        end
        if isfield(trials(i), 'events')
            trials(i).events = convert_to_table(trials(i).events, ...
                                                CATEGORICAL_FIELDS, add_datetime);
            if minimal
                trials(i).events = [];
            end
        end
        if isfield(trials(i), 'mkv_frames')
            trials(i).mkv_frames = convert_to_table(trials(i).mkv_frames, ...
                                                     CATEGORICAL_FIELDS, add_datetime);
        end
        if isfield(trials(i), 'mini2p_frames')
            trials(i).mini2p_frames = convert_to_table(trials(i).mini2p_frames, ...
                                                        CATEGORICAL_FIELDS, add_datetime);
        end
        for field = ["cue1", "cue2", "correct_side", "chosen_side", "outcome", "trial_type"]
            name = char(field);
            if isfield(trials(i), name) && (ischar(trials(i).(name)) || isstring(trials(i).(name)))
                value = trials(i).(name);
                if ~isempty(value)
                    trials(i).(name) = categorical({char(value)});
                end
            end
        end
    end
    session.trials = trials;
end
end


function out = convert_to_table(value, categorical_fields, add_datetime)
if isempty(value)
    out = table();
    return
end
if istable(value)
    out = value;
    return
end
if ~isstruct(value)
    out = value;
    return
end

field_names = fieldnames(value);
if isempty(field_names)
    out = table();
    return
end

lengths = zeros(1, numel(field_names));
for i = 1:numel(field_names)
    v = value.(field_names{i});
    lengths(i) = numel(v);
end
if any(diff(lengths) ~= 0) || lengths(1) == 0
    out = value;
    return
end

columns = struct();
for i = 1:numel(field_names)
    name = field_names{i};
    v = value.(name);
    if iscell(v) && ~isempty(v) && (ischar(v{1}) || isstring(v{1}))
        v = string(v);
    end
    if isvector(v) && size(v, 2) > 1
        v = v(:);
    end
    if any(strcmp(name, categorical_fields))
        v = categorical(v);
    end
    columns.(name) = v;
end

out = struct2table(columns);
if add_datetime && any(strcmp('pc_ts', out.Properties.VariableNames))
    out.pc_datetime = datetime(out.pc_ts, 'ConvertFrom', 'posixtime');
end
end


function result = version_less_than(left, right)
left_parts = parse_version(left);
right_parts = parse_version(right);
n = max(numel(left_parts), numel(right_parts));
left_parts(end + 1:n) = 0;
right_parts(end + 1:n) = 0;
result = false;
for i = 1:n
    if left_parts(i) < right_parts(i)
        result = true;
        return
    elseif left_parts(i) > right_parts(i)
        return
    end
end
end


function parts = parse_version(value)
tokens = regexp(char(value), '\d+', 'match');
parts = zeros(1, numel(tokens));
for i = 1:numel(tokens)
    parts(i) = str2double(tokens{i});
end
end
