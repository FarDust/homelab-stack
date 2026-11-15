# Historical deployment comment omitted from synthetic fixture.
# Historical deployment comment omitted from synthetic fixture.
# Historical deployment comment omitted from synthetic fixture.
# Historical deployment comment omitted from synthetic fixture.
# Historical deployment comment omitted from synthetic fixture.
# Historical deployment comment omitted from synthetic fixture.
# Historical deployment comment omitted from synthetic fixture.
# Historical deployment comment omitted from synthetic fixture.
# Historical deployment comment omitted from synthetic fixture.
LANES_HOME=${LANES_HOME:-$HOME/ci-fallback}
LANES_LEDGER=${LANES_LEDGER:-$LANES_HOME/ledger.jsonl}
LANES_SLOTS=${LANES_SLOTS:-$LANES_HOME/slots}  # port claims only (slots/ports)
LANES_MAX_TOTAL=${LANES_MAX_TOTAL:-6}          # host budget: cpu-heavy + browser jobs across ALL agents = 8 GB of agent memory / 2.5 GB per tmpfs job (saturation lane, 2026-11-13T00:17Z)
LANES_MAX_BROWSER=${LANES_MAX_BROWSER:-3}      # of which browser (Playwright container) jobs
LANES_PRIORITY_PSI_BONUS=${LANES_PRIORITY_PSI_BONUS:-15} # priority by value (integrator*/release*): starts at START_PSI + this, never above the abort threshold; non-priority jobs run niced
LANES_START_PSI=${LANES_START_PSI:-40}         # admit while cpu PSI some avg10 is below this
LANES_ABORT_PSI=${LANES_ABORT_PSI:-60}         # stop the youngest job at or above this
# Historical deployment comment omitted from synthetic fixture.
# Historical deployment comment omitted from synthetic fixture.
# Historical deployment comment omitted from synthetic fixture.
LANES_MAX_SWAPOUT_PAGES=${LANES_MAX_SWAPOUT_PAGES:-1280} # admit while pswpout grows by fewer pages than this in 5 s (1 MB/s)
LANES_MIN_SWAP_FREE_KB=${LANES_MIN_SWAP_FREE_KB:-3145728} # and SwapFree is at least this (3 GB; was 0 until 2026-11-13, swap exhaustion took the node down at 13:02Z)
LANES_START_MEM_PSI=${LANES_START_MEM_PSI:-10} # admit while memory PSI some avg10 is below this
LANES_ABORT_MEM_PSI=${LANES_ABORT_MEM_PSI:-50} # stop the youngest job when memory PSI some avg10 stays at or above this ...
LANES_ABORT_MEM_HOLD_S=${LANES_ABORT_MEM_HOLD_S:-30}  # ... for this long
# Historical deployment comment omitted from synthetic fixture.
export NODE_OPTIONS=${NODE_OPTIONS:---max-old-space-size=1536}
LANES_ABORT_LOAD=${LANES_ABORT_LOAD:-12}       # or at this load1 together with cpu PSI at or above the start threshold
LANES_MIN_ROOT_FREE_KB=${LANES_MIN_ROOT_FREE_KB:-3145728}   # npm ci is refused under 3 GB free on /
LANES_ADMIT_WAIT_S=${LANES_ADMIT_WAIT_S:-3600} # bound of the admission wait; reaching it is a failure with a ledger row
LANES_WHO=${LANES_WHO:-unspecified}            # lane or agent name; set it so the ledger says who runs what
# Historical deployment comment omitted from synthetic fixture.
# Historical deployment comment omitted from synthetic fixture.
LANES_JOBS_ROOT=${LANES_JOBS_ROOT:-/dev/shm/agent-jobs}       # per-job scratch: checkout, node_modules, temp, working evidence
LANES_JOB_MEM_KB=${LANES_JOB_MEM_KB:-2621440}                # expected footprint of one job with tmpfs scratch (2.5 GB); state yours
# Historical deployment comment omitted from synthetic fixture.
LANES_JOB_MEM_KB_CHECK=${LANES_JOB_MEM_KB_CHECK:-3407872}
# Historical deployment comment omitted from synthetic fixture.
# Historical deployment comment omitted from synthetic fixture.
# Historical deployment comment omitted from synthetic fixture.
LANES_SWAP_DEV=${LANES_SWAP_DEV-$(basename "$(readlink -f "$(awk 'NR==2{print $1}' /proc/swaps 2>/dev/null)" 2>/dev/null)" 2>/dev/null)}
LANES_MAX_SWAP_AWAIT_MS=${LANES_MAX_SWAP_AWAIT_MS:-40}
LANES_START_IO_FULL=${LANES_START_IO_FULL:-20}
LANES_PRIORITY_IO_FULL_BONUS=${LANES_PRIORITY_IO_FULL_BONUS:-10}
LANES_PRIORITY_AWAIT_BONUS_MS=${LANES_PRIORITY_AWAIT_BONUS_MS:-20}
LANES_MIN_MEM_AVAIL_KB=${LANES_MIN_MEM_AVAIL_KB:-3145728}    # headroom (MemAvailable - SReclaimable) that must remain after the job's footprint (3 GB)
LANES_JOB_DIR_MAX_IDLE_MIN=${LANES_JOB_DIR_MAX_IDLE_MIN:-15}  # a job dir whose creating process is gone is swept after this idle time (tmpfs left behind is swap load)
# Historical deployment comment omitted from synthetic fixture.
# Historical deployment comment omitted from synthetic fixture.
# Historical deployment comment omitted from synthetic fixture.
# Historical deployment comment omitted from synthetic fixture.
# Historical deployment comment omitted from synthetic fixture.
# Historical deployment comment omitted from synthetic fixture.
LANES_CPU_BUDGET=${LANES_CPU_BUDGET:-1}
LANES_CPU_WEIGHT_PRIORITY=${LANES_CPU_WEIGHT_PRIORITY:-150}
LANES_CPU_WEIGHT=${LANES_CPU_WEIGHT:-40}
LANES_QUOTA_PRIORITY=${LANES_QUOTA_PRIORITY:-300}   # percent of one core
LANES_QUOTA_CHECK=${LANES_QUOTA_CHECK:-200}
LANES_QUOTA=${LANES_QUOTA:-100}
export UV_THREADPOOL_SIZE=${UV_THREADPOOL_SIZE:-2} VITEST_MAX_THREADS=${VITEST_MAX_THREADS:-2} VITEST_MAX_WORKERS=${VITEST_MAX_WORKERS:-2} OMP_NUM_THREADS=${OMP_NUM_THREADS:-2} RAYON_NUM_THREADS=${RAYON_NUM_THREADS:-2}
# Historical deployment comment omitted from synthetic fixture.
_lanes_cpu_policy() {
  local what=${1:-}
  if _lanes_priority_who "${LANES_WHO:-}"; then LANES_CPU_W=$LANES_CPU_WEIGHT_PRIORITY; LANES_CPU_Q=$LANES_QUOTA_PRIORITY
  else
    LANES_CPU_W=$LANES_CPU_WEIGHT
    case "$what" in *check*|*gates*) LANES_CPU_Q=$LANES_QUOTA_CHECK ;; *) LANES_CPU_Q=$LANES_QUOTA ;; esac
  fi
  LANES_DOCKER_CPU="--cpus=$(awk -v q="$LANES_CPU_Q" 'BEGIN{printf "%.2f", q/100}') --cpu-shares=$(( LANES_CPU_W * 10 ))"
}
LANES_CPU_W=$LANES_CPU_WEIGHT LANES_CPU_Q=$LANES_QUOTA LANES_DOCKER_CPU="--cpus=1.00 --cpu-shares=$(( LANES_CPU_WEIGHT * 10 ))"   # defaults until lanes_admit applies the policy of the job
LANES_SCOPE="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/lanes-scope"   # wrapper that runs a command in the job scope: "$LANES_SCOPE" -- <command...>
# Historical deployment comment omitted from synthetic fixture.
# Historical deployment comment omitted from synthetic fixture.
# Historical deployment comment omitted from synthetic fixture.
LANES_SHM_BUDGET_KB=${LANES_SHM_BUDGET_KB:-8388608}   # 8 GB of the 16 GB tmpfs (was 10 GB); the rest is memory the node needs
LANES_SHM_NEW_KB=${LANES_SHM_NEW_KB:-1048576}
export UV_LINK_MODE=${UV_LINK_MODE:-symlink}
shm_used_kb() { df -Pk /dev/shm | awk 'NR==2{print $3}'; }
GATE_DESC="node-wide admission, no lock: start when memory PSI some avg10 < $LANES_START_MEM_PSI, cpu PSI some avg10 < $LANES_START_PSI, swap-out < $LANES_MAX_SWAPOUT_PAGES pages in 5 s, headroom (MemAvailable - SReclaimable) >= job $((LANES_JOB_MEM_KB/1024)) MB + $((LANES_MIN_MEM_AVAIL_KB/1024)) MB, SwapFree >= $((LANES_MIN_SWAP_FREE_KB/1024)) MB, and the ledger shows fewer than $LANES_MAX_TOTAL cpu-heavy+browser jobs running on the host; the youngest job stops when memory PSI some avg10 >= $LANES_ABORT_MEM_PSI for ${LANES_ABORT_MEM_HOLD_S}s or cpu PSI some avg10 >= $LANES_ABORT_PSI, or load1 >= $LANES_ABORT_LOAD with cpu PSI >= $LANES_START_PSI (Gabriel 2026-11-12T23:37Z; thresholds from the saturation lane 2026-11-13T00:17Z)"
psi10() { awk '/^some/{split($2,a,"="); printf "%d", a[2]}' "/proc/pressure/$1"; }
load() { cut -d" " -f1 /proc/loadavg | cut -d. -f1; }
mem_avail_kb() { awk '/^MemAvailable:/{print $2}' /proc/meminfo; }
shm_avail_kb() { df -Pk /dev/shm | awk 'NR==2{print $4}'; }
headroom_kb() { awk '/^MemAvailable:/{a=$2} /^SReclaimable:/{s=$2} END{print a-s}' /proc/meminfo; }
swap_free_kb() { awk '/^SwapFree:/{print $2}' /proc/meminfo; }
swapout_pages_5s() { local a; a=$(awk '/^pswpout /{print $2}' /proc/vmstat); sleep 5; echo $(( $(awk '/^pswpout /{print $2}' /proc/vmstat) - a )); }
psi_full10() { awk '/^full/{split($2,a,"="); printf "%d", a[2]}' "/proc/pressure/$1" 2>/dev/null; }
# Historical deployment comment omitted from synthetic fixture.
swap_await_ms() { local d=${LANES_SWAP_DEV:-} a b; [ -n "$d" ] && grep -q " $d " /proc/diskstats 2>/dev/null || { echo 0; return; }
  a=$(awk -v d="$d" '$3==d{print $4+$8, $7+$11}' /proc/diskstats); sleep 2; b=$(awk -v d="$d" '$3==d{print $4+$8, $7+$11}' /proc/diskstats)
  awk -v a="$a" -v b="$b" 'BEGIN{split(a,x," ");split(b,y," ");n=y[1]-x[1]; if(n<20)print 0; else printf "%d", (y[2]-x[2])/n}'; }
mem_ok() { [ $(( $(headroom_kb) - LANES_JOB_MEM_KB )) -ge "$LANES_MIN_MEM_AVAIL_KB" ] && [ "$(shm_avail_kb)" -ge "$LANES_JOB_MEM_KB" ]; }
on_tmpfs() { [ "$(stat -f -c %T "$1" 2>/dev/null)" = tmpfs ]; }
gate_open() { [ "$(psi10 cpu)" -lt "$LANES_START_PSI" ] && [ "$(psi10 memory)" -lt "$LANES_START_MEM_PSI" ]; }
# Historical deployment comment omitted from synthetic fixture.
# Historical deployment comment omitted from synthetic fixture.
# Historical deployment comment omitted from synthetic fixture.
# Historical deployment comment omitted from synthetic fixture.
_lanes_mem_hit() {
  local f="$LANES_SLOTS/mem-high.$$"
  if [ "$(psi10 memory)" -ge "$LANES_ABORT_MEM_PSI" ]; then
    [ -e "$f" ] || { mkdir -p "$LANES_SLOTS"; : > "$f"; }
    [ $(( $(date +%s) - $(stat -c %Y "$f") )) -ge "$LANES_ABORT_MEM_HOLD_S" ]
  else rm -f "$f"; return 1; fi
}
gate_hit() { local c; c=$(psi10 cpu); _lanes_mem_hit || [ "$c" -ge "$LANES_ABORT_PSI" ] || { [ "$(load)" -ge "$LANES_ABORT_LOAD" ] && [ "$c" -ge "$LANES_START_PSI" ]; }; }
measure() { echo "load=$(cut -d' ' -f1-3 /proc/loadavg | tr ' ' '/') cpu_some_avg10=$(psi10 cpu) mem_some_avg10=$(psi10 memory) io_some_avg10=$(psi10 io) mem_avail_mb=$(( $(mem_avail_kb) / 1024 ))"; }
# Historical deployment comment omitted from synthetic fixture.
# Historical deployment comment omitted from synthetic fixture.
# Historical deployment comment omitted from synthetic fixture.
# Historical deployment comment omitted from synthetic fixture.
_lanes_thr_snap() { local d; for d in /sys/fs/cgroup/system.slice/*/ /sys/fs/cgroup/user.slice/user-*.slice/user@*.service/app.slice/*/; do [ -r "${d}cpu.stat" ] && echo "$d $(awk "/^nr_throttled/{print \$2}" "${d}cpu.stat")"; done; }
shadow_signals() {
  local s1 s2 i1 t1 i2 t2 pe fc dq
  s1=$(_lanes_thr_snap 2>/dev/null); read -r _ _ _ _ i1 _ < <(grep "^cpu " /proc/stat); t1=$(awk "/^cpu /{s=0;for(i=2;i<=9;i++)s+=\$i;print s}" /proc/stat); sleep 3
  s2=$(_lanes_thr_snap 2>/dev/null); read -r _ _ _ _ i2 _ < <(grep "^cpu " /proc/stat); t2=$(awk "/^cpu /{s=0;for(i=2;i<=9;i++)s+=\$i;print s}" /proc/stat)
  pe=$(join <(printf "%s\n" "$s1" | sort) <(printf "%s\n" "$s2" | sort) 2>/dev/null | awk "\$2==\$3{print \$1}" | while read -r d; do awk "/^some/{split(\$2,a,\"=\"); printf \"%d\n\", a[2]}" "${d}cpu.pressure" 2>/dev/null; done | sort -n | tail -1)
  dq=$(tail -n 400 "$LANES_LEDGER" 2>/dev/null | jq -rs --argjson now "$(date +%s)" "[.[]|select(.event==\"start\" and .cpu_quota_pct!=null and (.ts|fromdateiso8601)>(\$now-60))|.cpu_quota_pct]|add//0" 2>/dev/null)
  fc=$(awk -v i1="${i1:-0}" -v i2="${i2:-0}" -v t1="${t1:-0}" -v t2="${t2:-0}" -v n="$(nproc)" -v q="${dq:-0}" "BEGIN{ if (t2>t1) printf \"%.2f\", n*(i2-i1)/(t2-t1) - q/100; else printf \"null\" }")
  printf "\"psi_excl_throttled\":%s,\"fit_free_cores\":%s,\"shadow\":true" "${pe:-null}" "${fc:-null}"
  return 0
}
root_free_ok() { [ "$(df -Pk / | awk 'NR==2{print $4}')" -ge "$LANES_MIN_ROOT_FREE_KB" ]; }
# Historical deployment comment omitted from synthetic fixture.
LANES_RUN=$$
LANES_ID="$(date -u +%Y%m%dT%H%M%SZ)-$LANES_RUN"
# Historical deployment comment omitted from synthetic fixture.
# Historical deployment comment omitted from synthetic fixture.
export LANES_ID LANES_WHO
LANES_JRA_BIN="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/bin"
[ -x "$LANES_JRA_BIN/docker" ] && case ":$PATH:" in ":$LANES_JRA_BIN:"*) ;; *) export PATH="$LANES_JRA_BIN:$PATH" ;; esac

_lanes_json() { local s=$1; s=${s//\\/\\\\}; s=${s//\"/\\\"}; s=${s//$'\n'/ }; s=${s//$'\t'/ }; printf '%s' "$s" | tr -d '\000-\037'; }
_lanes_class() { case $1 in plain|cpu-heavy) echo cpu-heavy ;; browser|light) echo "$1" ;; *) return 2 ;; esac; }
# Historical deployment comment omitted from synthetic fixture.
# Historical deployment comment omitted from synthetic fixture.
# Historical deployment comment omitted from synthetic fixture.
# Historical deployment comment omitted from synthetic fixture.
lanes_ledger() {
  local event=$1 class=$2 what=$3 where=$4 extra=${5:-}
  local bin=${LANES_LEDGER_BIN:-${LANES_HOME}/ledger-publisher/.venv/bin/ledger-publisher}
  local -a base=()
  case "$extra" in *'"cpu_some_avg10"'*) ;; *) base=(--cpu-some-avg10 "$(psi10 cpu)" --mem-some-avg10 "$(psi10 memory)") ;; esac
  mkdir -p "$(dirname "$LANES_LEDGER")" || return 1
  [ -x "$bin" ] || { echo "lanes_ledger: $bin is not executable (uv sync in ${LANES_HOME}/ledger-publisher)" >&2; return 1; }
  "$bin" append --ledger "$LANES_LEDGER" --event="$event" --class="$class" --what="$what" --where="$where" \
    --id="$LANES_ID" --who="$LANES_WHO" --host="$(hostname)" --pid="$$" \
    --io-some-avg10 "$(psi10 io)" --load1 "$(cut -d' ' -f1 /proc/loadavg)" --mem-avail-mb "$(( $(mem_avail_kb) / 1024 ))" \
    ${base[@]+"${base[@]}"} ${extra:+--extra-members="$extra"} --degrade-invalid
}
_lanes_start_of() { sed 's/.*) //' "/proc/$1/stat" 2>/dev/null | awk '{print $20}'; }
# Historical deployment comment omitted from synthetic fixture.
# Historical deployment comment omitted from synthetic fixture.
# Historical deployment comment omitted from synthetic fixture.
lanes_running() {
  local pid class id ts born
  [ -s "$LANES_LEDGER" ] || return 0
  tail -n 4000 "$LANES_LEDGER" | jq -nrR --arg h "$(hostname)" '[inputs | fromjson? | select(type == "object" and .host == $h and .id != null)]
      | to_entries | map(.value + {pos: .key}) | group_by(.id) | map(last)
      | map(select(.event == "start" and (.pid | type) == "number")) | sort_by(.pos) | .[] | "\(.pid) \(.class // "cpu-heavy") \(.id) \(.ts)"' 2>/dev/null |
  while read -r pid class id ts; do
    [ -d "/proc/$pid" ] || continue
    born=$(_lanes_start_of "$pid"); [ -n "$born" ] || continue
    born=$(( $(awk '/^btime/{print $2}' /proc/stat) + born / $(getconf CLK_TCK) ))
    [ "$born" -le $(( $(date -u -d "$ts" +%s 2>/dev/null || echo 0) + 5 )) ] || continue
    case $class in plain) class=cpu-heavy ;; cpu-heavy|browser) ;; *) continue ;; esac
    echo "$pid $class $id"
  done
}
# Historical deployment comment omitted from synthetic fixture.
# Historical deployment comment omitted from synthetic fixture.
_lanes_priority_who() { case "$1" in integrator*|release*|recorder4*) return 0 ;; *) return 1 ;; esac; }
_lanes_who_of_id() { grep -m1 "\"id\":\"$1\"" "$LANES_LEDGER" 2>/dev/null | jq -r '.who // ""' 2>/dev/null; }
# Historical deployment comment omitted from synthetic fixture.
# Historical deployment comment omitted from synthetic fixture.
_lanes_room() {
  local class=$1 own=${2:-} run total browser
  local max=$LANES_MAX_TOTAL; case "${LANES_WHO:-}" in integrator*|release*|recorder4*) max=$(( max + 1 ));; esac  # one extra place for merge/release gates: priority by value, still bounded by the measured signals
  run=$(lanes_running)
  if [ -n "$own" ]; then run=$(printf '%s\n' "$run" | awk -v id="$own" '{print} $3==id{exit}'); fi
  total=$(printf '%s\n' "$run" | grep -c . ); browser=$(printf '%s\n' "$run" | grep -c ' browser ')
  if [ -n "$own" ]; then
    [ "$total" -le "$max" ] && { [ "$class" != browser ] || [ "$browser" -le "$LANES_MAX_BROWSER" ]; }
  else
    [ "$total" -lt "$max" ] && { [ "$class" != browser ] || [ "$browser" -lt "$LANES_MAX_BROWSER" ]; }
  fi
}
# Historical deployment comment omitted from synthetic fixture.
# Historical deployment comment omitted from synthetic fixture.
# Historical deployment comment omitted from synthetic fixture.
# Historical deployment comment omitted from synthetic fixture.
lanes_admit() {
  local class what=$2 where=$3 expected=${4:-0} t0 why
  class=$(_lanes_class "$1") || { echo "lanes_admit: class must be browser, cpu-heavy (or plain) or light, got: $1" >&2; return 2; }
  t0=$(date +%s)
  lanes_sweep_job_dirs >/dev/null 2>&1
  while [ "$class" != light ]; do
# Historical deployment comment omitted from synthetic fixture.
    local m_mem m_cpu m_swp m_head m_swf sig
    m_mem=$(psi10 memory); m_cpu=$(psi10 cpu); m_swp=$(swapout_pages_5s); m_head=$(headroom_kb); m_swf=$(swap_free_kb)
    sig="\"shm_new_kb\":$LANES_SHM_NEW_KB,\"shm_budget_kb\":$LANES_SHM_BUDGET_KB,\"shm_used_mb\":$(( $(shm_used_kb) / 1024 )),\"mem_some_avg10\":$m_mem,\"cpu_some_avg10\":$m_cpu,\"swapout_pages_5s\":$m_swp,\"headroom_mb\":$(( m_head / 1024 )),\"swap_free_mb\":$(( m_swf / 1024 ))"
    why=""
    local job_kb=$LANES_JOB_MEM_KB; case "$what" in *check*|*gates*) job_kb=$LANES_JOB_MEM_KB_CHECK ;; esac
    local m_iof m_awt io_max=$LANES_START_IO_FULL awt_max=$LANES_MAX_SWAP_AWAIT_MS; m_iof=$(psi_full10 io); m_awt=$(swap_await_ms)
    _lanes_priority_who "${LANES_WHO:-}" && { io_max=$(( io_max + LANES_PRIORITY_IO_FULL_BONUS )); awt_max=$(( awt_max + LANES_PRIORITY_AWAIT_BONUS_MS )); }
    sig="$sig,$(shadow_signals 2>/dev/null || true),\"io_full_avg10\":${m_iof:-0},\"swap_await_ms\":${m_awt:-0},\"job_kb\":$job_kb"
    local mem_start=$LANES_START_MEM_PSI swp_max=$LANES_MAX_SWAPOUT_PAGES; _lanes_priority_who "${LANES_WHO:-}" && { mem_start=$(( LANES_START_MEM_PSI + 10 )); swp_max=$(( LANES_MAX_SWAPOUT_PAGES * 8 )); }   # priority by value: one critical job may start under moderate memory pressure; the abort rule still bounds it
    [ "$m_mem" -lt "$mem_start" ] || why="memory PSI some avg10 $m_mem >= $mem_start"
    _lanes_cpu_policy "$what"
    local psi_start=$LANES_START_PSI; _lanes_priority_who "${LANES_WHO:-}" && psi_start=$(( LANES_START_PSI + LANES_PRIORITY_PSI_BONUS ))
    [ -z "$why" ] && [ "$m_cpu" -ge "$psi_start" ] && why="cpu PSI some avg10 $m_cpu >= $psi_start"
    [ -z "$why" ] && [ "$m_swp" -ge "$swp_max" ] && why="swap-out $m_swp pages in 5 s >= $swp_max"
    [ -z "$why" ] && [ "${m_iof:-0}" -ge "$io_max" ] && why="io PSI full avg10 $m_iof >= $io_max"
    [ -z "$why" ] && [ "${m_awt:-0}" -ge "$awt_max" ] && why="swap device ${LANES_SWAP_DEV} await ${m_awt} ms >= ${awt_max} ms"
    [ -z "$why" ] && [ $(( m_head - job_kb )) -lt "$LANES_MIN_MEM_AVAIL_KB" ] && why="headroom $(( m_head / 1024 )) MB < job $(( job_kb / 1024 )) MB + $(( LANES_MIN_MEM_AVAIL_KB / 1024 )) MB"
    [ -z "$why" ] && [ "$m_swf" -lt "$LANES_MIN_SWAP_FREE_KB" ] && why="SwapFree $(( m_swf / 1024 )) MB < $(( LANES_MIN_SWAP_FREE_KB / 1024 )) MB"
    [ -z "$why" ] && [ "$class" != light ] && [ $(( $(shm_used_kb) + LANES_SHM_NEW_KB )) -gt "$LANES_SHM_BUDGET_KB" ] && why="/dev/shm used $(( $(shm_used_kb) / 1024 )) MB + new tree $(( LANES_SHM_NEW_KB / 1024 )) MB > budget $(( LANES_SHM_BUDGET_KB / 1024 )) MB"
    [ -z "$why" ] && [ "$(shm_avail_kb)" -lt "$LANES_JOB_MEM_KB" ] && why="/dev/shm free $(( $(shm_avail_kb) / 1024 )) MB < job $(( LANES_JOB_MEM_KB / 1024 )) MB"
    [ -z "$why" ] && ! _lanes_room "$class" && why="host budget: $(lanes_running | grep -c .) running ($(lanes_running | grep -c ' browser ') browser) of $LANES_MAX_TOTAL ($LANES_MAX_BROWSER browser)"
    if [ -z "$why" ]; then
      lanes_ledger start "$class" "$what" "$where" "\"expected_s\":$expected,\"expected_min\":$(( (expected + 59) / 60 )),\"waited_s\":$(( $(date +%s) - t0 )),\"where_fs\":\"$(stat -f -c %T "$where" 2>/dev/null)\",\"job_mb\":$(( job_kb / 1024 )),\"cpu_weight\":$LANES_CPU_W,\"cpu_quota_pct\":$LANES_CPU_Q,$sig" || { echo "lanes_admit: cannot write $LANES_LEDGER" >&2; return 1; }
      _lanes_room "$class" "$LANES_ID" && break
      why="host budget: another job took the last place in the same instant"
    fi
    if [ $(( $(date +%s) - t0 )) -ge "$LANES_ADMIT_WAIT_S" ]; then
      lanes_ledger refused "$class" "$what" "$where" "\"reason\":\"$(_lanes_json "$why"); no room for ${LANES_ADMIT_WAIT_S}s\",$sig"
      echo "lanes_admit: refused after ${LANES_ADMIT_WAIT_S}s: $why" >&2; return 1
    fi
    local gch=""; case "$why" in */dev/shm*) gch=$(_lanes_gc_hint_json "$where") ;; esac   # tmpfs budget: hint which of the caller's own superseded trees could be reclaimed (no deletion)
    lanes_ledger deferred "$class" "$what" "$where" "\"reason\":\"$(_lanes_json "$why")\",\"waited_s\":$(( $(date +%s) - t0 )),$sig${gch:+,$gch}"
    sleep $(( 30 + RANDOM % 61 ))
  done
  [ "$class" = light ] && { lanes_ledger start "$class" "$what" "$where" "\"expected_s\":$expected,\"expected_min\":$(( (expected + 59) / 60 )),\"waited_s\":0" || return 1; }
  export LANES_WHAT=$what
  [ -n "${LANES_HEAD:-}" ] || { [[ $where =~ -[a-z]([0-9a-f]{7,40})(/|$) ]] && export LANES_HEAD=${BASH_REMATCH[1]}; }
  LANES_OPEN=1; LANES_CLASS=$class; LANES_WHAT=$what; LANES_WHERE=$where; LANES_T0=$(date +%s)
  case "$where" in "$LANES_JOBS_ROOT"/*) touch "$(echo "$where" | cut -d/ -f1-5)/.last-used" 2>/dev/null ;; esac
  return 0
}
# Historical deployment comment omitted from synthetic fixture.
lanes_done() {
  [ -n "${LANES_OPEN:-}" ] || return 0
  LANES_OPEN=""
  [ -e "$LANES_JOBS_ROOT/$LANES_ID/.agent-job" ] && rm -rf "$LANES_JOBS_ROOT/$LANES_ID"
  lanes_ledger end "$LANES_CLASS" "$LANES_WHAT" "$LANES_WHERE" "\"shm_used_mb\":$(( $(shm_used_kb) / 1024 )),\"tree_mb\":$(case "$LANES_WHERE" in "$LANES_JOBS_ROOT"/*) du -sm "$(echo "$LANES_WHERE" | cut -d/ -f1-5)" 2>/dev/null | cut -f1 | grep -E '^[0-9]+$' || echo 0 ;; *) echo 0 ;; esac),\"result\":\"exit=$1\",\"duration_s\":$(( $(date +%s) - LANES_T0 ))${2:+,\"note\":\"$(_lanes_json "$2")\"}" || echo "WARN ledger write failed: $LANES_LEDGER" >&2
  ( lanes_reap_job_containers ) >/dev/null 2>&1   # end hook: the job removes the containers it started that are still running
  ( lanes_gc_hook ) >/dev/null 2>&1   # end hook: the lane removes its own superseded head trees (tree gc, 2026-11-13); never changes the exit status
  return 0
}
# Historical deployment comment omitted from synthetic fixture.
# Historical deployment comment omitted from synthetic fixture.
lanes_should_abort() {
  gate_hit || return 1
  _lanes_priority_who "${LANES_WHO:-}" && return 1   # a priority job is not the victim
  local victim="" id
  while read -r _ _ id; do _lanes_priority_who "$(_lanes_who_of_id "$id")" || victim=$id; done < <(lanes_running)   # youngest non-priority job
  [ -n "$victim" ] || victim=$(lanes_running | tail -1 | cut -d' ' -f3)   # only priority jobs left: old rule
  [ "$victim" = "$LANES_ID" ] || return 1
  mkdir -p "$LANES_SLOTS"
  [ -e "$LANES_SLOTS/last-abort" ] && [ $(( $(date +%s) - $(stat -c %Y "$LANES_SLOTS/last-abort") )) -lt 60 ] && return 1
  : > "$LANES_SLOTS/last-abort"; return 0
}
# Historical deployment comment omitted from synthetic fixture.
# Historical deployment comment omitted from synthetic fixture.
lanes_free_port() {
  local p=$(( $1 + $$ % 400 )) n=0 f owner
  mkdir -p "$LANES_SLOTS/ports" || return 1
  for f in "$LANES_SLOTS"/ports/*; do [ -e "$f" ] || continue; owner=$(cat "$f" 2>/dev/null); [ "$(_lanes_start_of "${owner%% *}")" = "${owner##* }" ] || rm -f "$f"; done
  while [ $n -le 400 ]; do
    f="$LANES_SLOTS/ports/$p"
    if ! ss -Hltn "sport = :$p" 2>/dev/null | grep -q . && ( set -C; echo "$$ $(_lanes_start_of $$)" > "$f" ) 2>/dev/null; then echo "$p"; return 0; fi
    p=$(( p + 1 )); n=$(( n + 1 ))
  done
  return 1
}
# Historical deployment comment omitted from synthetic fixture.
# Historical deployment comment omitted from synthetic fixture.
# Historical deployment comment omitted from synthetic fixture.
lanes_job_dir() {
  local d="$LANES_JOBS_ROOT/$LANES_ID"
  [ -n "${1:-}" ] && d="$LANES_JOBS_ROOT/$(printf '%s' "$LANES_WHO-$1" | tr -c 'A-Za-z0-9._-' '_')"
  [ "$(shm_avail_kb)" -ge 262144 ] || { echo "lanes_job_dir: refused, /dev/shm has $(( $(shm_avail_kb) / 1024 )) MB free" >&2; return 3; }
  mkdir -p "$d" && printf 'who=%s id=%s created=%s\n%s %s\n' "$LANES_WHO" "$LANES_ID" "$(date -u +%FT%TZ)" "$$" "$(_lanes_start_of $$)" > "$d/.agent-job" && touch "$d/.last-used" && echo "$d"
}
lanes_job_dir_rm() { case "$1" in "$LANES_JOBS_ROOT"/?*) [ -e "$1/.agent-job" ] && rm -rf "$1" ;; *) echo "lanes_job_dir_rm: not a job dir: $1" >&2; return 2 ;; esac; }
# Historical deployment comment omitted from synthetic fixture.
# Historical deployment comment omitted from synthetic fixture.
# Historical deployment comment omitted from synthetic fixture.
lanes_sweep_job_dirs() {
  local d owner
  for d in "$LANES_JOBS_ROOT"/*/; do
    d=${d%/}; [ -e "$d/.agent-job" ] || continue
    owner=$(sed -n 2p "$d/.agent-job" 2>/dev/null); [ -n "$owner" ] || continue
    [ "$(_lanes_start_of "${owner%% *}")" = "${owner##* }" ] && continue
    [ -n "$(find "$d/.last-used" -mmin "-$LANES_JOB_DIR_MAX_IDLE_MIN" 2>/dev/null)" ] && continue
    pgrep -f -- "$d" >/dev/null 2>&1 && continue
    rm -rf "$d" && echo "swept $d"
  done
}
# Historical deployment comment omitted from synthetic fixture.
# Historical deployment comment omitted from synthetic fixture.
# Historical deployment comment omitted from synthetic fixture.
# Historical deployment comment omitted from synthetic fixture.
# Historical deployment comment omitted from synthetic fixture.
# Historical deployment comment omitted from synthetic fixture.
# Historical deployment comment omitted from synthetic fixture.
# Historical deployment comment omitted from synthetic fixture.
# Historical deployment comment omitted from synthetic fixture.
LANES_GC=${LANES_GC:-1}
LANES_GC_MIN_AGE_MIN=${LANES_GC_MIN_AGE_MIN:-10}
LANES_GC_REPORT_AGE_H=${LANES_GC_REPORT_AGE_H:-6}
_lanes_gc_who_ok() { [[ "${LANES_WHO:-}" =~ ^[A-Za-z0-9._-]+$ ]] && [ "$LANES_WHO" != unspecified ]; }
# Historical deployment comment omitted from synthetic fixture.
_lanes_tree_live() {
  local d=$1 p c
  pgrep -f -- "$d" >/dev/null 2>&1 && return 0
  for p in /proc/[0-9]*; do
    c=$(readlink "$p/cwd" 2>/dev/null) || continue
    case "$c" in "$d"|"$d"/*) return 0 ;; esac
  done
  if [ -z "${_LANES_GC_MOUNTS+x}" ]; then
    _LANES_GC_MOUNTS=$(timeout 10 docker ps -q 2>/dev/null | xargs -r timeout 10 docker inspect --format '{{range .Mounts}}{{println .Source}}{{end}}' 2>/dev/null)
  fi
  case "$_LANES_GC_MOUNTS" in *"$d"*) return 0 ;; esac
  return 1
}
# Historical deployment comment omitted from synthetic fixture.
_lanes_tree_idle_min() {
  local newest; newest=$(find "$1" -maxdepth 2 -printf '%T@\n' 2>/dev/null | sort -n | tail -1)
  [ -n "$newest" ] || { echo 0; return; }
  echo $(( ($(date +%s) - ${newest%.*}) / 60 ))
}
# Historical deployment comment omitted from synthetic fixture.
# Historical deployment comment omitted from synthetic fixture.
# Historical deployment comment omitted from synthetic fixture.
_lanes_gc_rm_root() {
  local d=$1 img c
  case "$d" in "$LANES_JOBS_ROOT"/?*) ;; *) return 1 ;; esac
  [ -d "$d" ] && [ ! -L "$d" ] || return 1
  for c in ${LANES_GC_IMAGE:-} alpine:3 alpine:3.20 busybox:latest; do [ -n "$c" ] && docker image inspect "$c" >/dev/null 2>&1 && { img=$c; break; }; done
  [ -n "${img:-}" ] || { echo "lanes_gc: no local cleanup image for $d" >&2; return 1; }
  timeout 180 docker run --rm --label "jra-gc=$LANES_WHO" --network none --read-only --cap-drop ALL --cap-add DAC_OVERRIDE --security-opt no-new-privileges     --pids-limit 64 --memory 128m -v "$d:/t" "$img" find /t -mindepth 1 -delete >/dev/null 2>&1
  rmdir -- "$d" 2>/dev/null
  [ ! -e "$d" ]
}
# Historical deployment comment omitted from synthetic fixture.
# Historical deployment comment omitted from synthetic fixture.
lanes_gc_own_trees() {
  local mode=${1:-hint} age=${2:-$LANES_GC_MIN_AGE_MIN} keep=${3:-${LANES_WHERE:-}} who=${LANES_WHO:-}
  [ "$LANES_GC" = 1 ] && _lanes_gc_who_ok || return 0
  unset _LANES_GC_MOUNTS
  local d b rest kind mt lu i mb idle
  local -A newest_of=()
  local -a names=() kinds=() mts=()
  for d in "$LANES_JOBS_ROOT"/"$who"-*/; do
    d=${d%/}; b=${d##*/}
    [ -d "$d" ] && [ ! -L "$d" ] && [ -O "$d" ] || continue
    rest=${b#"$who-"}; [[ $rest =~ ^([a-z])([0-9a-f]{7,40})$ ]] || continue
    kind=${BASH_REMATCH[1]}
    mt=$(stat -c %Y "$d" 2>/dev/null) || continue
    if [ -e "$d/.last-used" ]; then lu=$(stat -c %Y "$d/.last-used" 2>/dev/null) && [ "$lu" -gt "$mt" ] && mt=$lu; fi
    names+=("$b"); kinds+=("$kind"); mts+=("$mt")
    [ "$mt" -gt "${newest_of[$kind]:-0}" ] && newest_of[$kind]=$mt
  done
  for i in "${!names[@]}"; do
    [ "${mts[$i]}" -ge "${newest_of[${kinds[$i]}]}" ] && continue
    d=$LANES_JOBS_ROOT/${names[$i]}
    case "$keep" in "$d"|"$d"/*) continue ;; esac
    case "$PWD" in "$d"|"$d"/*) continue ;; esac
    _lanes_tree_live "$d" && continue
    idle=$(_lanes_tree_idle_min "$d"); [ "$idle" -ge "$age" ] || continue
    mb=$(du -sm "$d" 2>/dev/null | cut -f1)
    if [ "$mode" = remove ]; then
      rm -rf -- "$d" 2>/dev/null
      [ -e "$d" ] && _lanes_gc_rm_root "$d"   # root-owned files written by containers: the lane's own throwaway container removes the rest
      [ -e "$d" ] && { echo "lanes_gc: could not remove $d" >&2; continue; }
    fi
    echo "${names[$i]} ${mb:-0} $idle"
  done
  return 0
}
_lanes_gc_json() { jq -nRc '[inputs | split(" ") | {tree: .[0], mb: (.[1] | tonumber), idle_min: (.[2] | tonumber)}]'; }
# Historical deployment comment omitted from synthetic fixture.
_lanes_gc_hint_json() {
  local lines; lines=$(lanes_gc_own_trees hint "$LANES_GC_MIN_AGE_MIN" "${1:-}") || return 0
  [ -n "$lines" ] || return 0
  printf '"own_reclaimable_mb":%d,"own_reclaimable":%s' "$(printf '%s\n' "$lines" | awk '{s+=$2} END{print s+0}')" "$(printf '%s\n' "$lines" | _lanes_gc_json)"
}
# Historical deployment comment omitted from synthetic fixture.
# Historical deployment comment omitted from synthetic fixture.
# Historical deployment comment omitted from synthetic fixture.
_lanes_gc_report() {
  local d b o r w known tmp; tmp=$(mktemp) || return 0
  known=$(tail -n 4000 "$LANES_LEDGER" 2>/dev/null | jq -R -r 'fromjson? | .who? // empty' 2>/dev/null | sort -u)
  unset _LANES_GC_MOUNTS
  while IFS= read -r d; do
    [ -d "$d" ] && [ ! -L "$d" ] || continue; b=${d##*/}; o=""
    [ -e "$d/.agent-job" ] && o=$(sed -n '1s/^who=\([^ ]*\) .*/\1/p' "$d/.agent-job" 2>/dev/null)
    if [ -z "$o" ]; then
      while IFS= read -r w; do [ -n "$w" ] && [[ $b == "$w-"* ]] && [ "${#w}" -gt "${#o}" ] && o=$w; done <<< "$known"
    fi
    [ -n "$o" ] && [ "$o" != unspecified ] || continue
    tail -n 4000 "$LANES_LEDGER" 2>/dev/null | grep -F '"kind":"stale-tree-report"' | grep -qF "[$b]" && continue
    _lanes_tree_live "$d" && continue
    [ "$(_lanes_tree_idle_min "$d")" -ge $(( LANES_GC_REPORT_AGE_H * 60 )) ] || continue
    r=""; [ -n "$(find "$d" -not -user "$(id -un)" -print -quit 2>/dev/null)" ] && r=root-owned
    echo "$o $b $(du -sm "$d" 2>/dev/null | cut -f1) $(( $(_lanes_tree_idle_min "$d") / 60 )) ${r:-ok}" >> "$tmp"
  done < <(find "$LANES_JOBS_ROOT" -mindepth 1 -maxdepth 1 -type d -mmin +$(( LANES_GC_REPORT_AGE_H * 60 )) 2>/dev/null)
  for o in $(cut -d' ' -f1 "$tmp" | sort -u); do
    lanes_ledger note light "stale trees of $o older than ${LANES_GC_REPORT_AGE_H}h with no live process (reported, not deleted; the owner removes them): $(awk -v o="$o" '$1==o{printf "[%s] %s MB idle %s h%s; ", $2, $3, $4, ($5=="root-owned" ? " ROOT-OWNED (needs the owner'"'"'s gc container: lanes_gc_own_trees remove)" : "")}' "$tmp")" "$LANES_JOBS_ROOT" "\"kind\":\"stale-tree-report\",\"owner\":\"$o\",\"review\":\"owner next job end\""
  done
  rm -f "$tmp"
}
# Historical deployment comment omitted from synthetic fixture.
# Historical deployment comment omitted from synthetic fixture.
LANES_REAP=${LANES_REAP:-1}
lanes_reap_job_containers() {
  [ "$LANES_REAP" = 1 ] && command -v docker >/dev/null 2>&1 || return 0
  local ids names
  ids=$(timeout 20 docker ps -q --filter "label=jra-job=$LANES_ID" 2>/dev/null) || return 0
  [ -n "$ids" ] || return 0
  names=$(timeout 20 docker ps --filter "label=jra-job=$LANES_ID" --format '{{.Names}}' 2>/dev/null | paste -sd, -)
  timeout 60 docker rm -f $ids >/dev/null 2>&1
  lanes_ledger note light "end hook of an own job removed ${names:-containers} still running with label jra-job=$LANES_ID (lane $LANES_WHO)" "$LANES_JOBS_ROOT" "\"kind\":\"container-reap\",\"reaped\":\"$(_lanes_json "$names")\""
  return 0
}
# Historical deployment comment omitted from synthetic fixture.
# Historical deployment comment omitted from synthetic fixture.
_lanes_gc_report_containers() {
  command -v docker >/dev/null 2>&1 || return 0
  local tmp name who created age o; tmp=$(mktemp) || return 0
  while IFS='|' read -r name who created; do
    [ -n "$name" ] || continue
    [ -n "$who" ] || case "$name" in cif-*|jt-*) who="unknown owner" ;; *) continue ;; esac
    age=$(( ($(date +%s) - $(date -d "${created% UTC}" +%s 2>/dev/null || date +%s)) / 3600 ))
    [ "$age" -ge "$LANES_GC_REPORT_AGE_H" ] || continue
    tail -n 4000 "$LANES_LEDGER" 2>/dev/null | grep -F '"kind":"stale-container-report"' | grep -qF "[$name]" && continue
    echo "$who|$name|$age" >> "$tmp"
  done < <(timeout 20 docker ps --format '{{.Names}}|{{.Label "jra-who"}}|{{.CreatedAt}}' 2>/dev/null)
  while IFS= read -r o; do
    [ -n "$o" ] || continue
    lanes_ledger note light "containers of $o running longer than ${LANES_GC_REPORT_AGE_H}h (reported, not removed; the owner removes them): $(awk -F'|' -v o="$o" '$1==o{printf "[%s] up %s h; ", $2, $3}' "$tmp")" "$LANES_JOBS_ROOT" "\"kind\":\"stale-container-report\",\"owner\":\"$(_lanes_json "$o")\",\"review\":\"owner next job end\""
  done < <(cut -d'|' -f1 "$tmp" | sort -u)
  rm -f "$tmp"
}
# Historical deployment comment omitted from synthetic fixture.
# Historical deployment comment omitted from synthetic fixture.
lanes_gc_hook() {
  [ "$LANES_GC" = 1 ] && _lanes_gc_who_ok || return 0
  local removed mb
  removed=$(lanes_gc_own_trees remove "$LANES_GC_MIN_AGE_MIN" "${LANES_WHERE:-}")
  if [ -n "$removed" ]; then
    mb=$(printf '%s\n' "$removed" | awk '{s+=$2} END{print s+0}')
    lanes_ledger note light "tree gc by the end hook of an own job: removed $(printf '%s\n' "$removed" | grep -c .) superseded head tree(s) of lane $LANES_WHO ($mb MB); no live process, idle >= ${LANES_GC_MIN_AGE_MIN} min, newest head kept" "$LANES_JOBS_ROOT" "\"kind\":\"tree-gc\",\"gc_freed_mb\":$mb,\"gc_removed\":$(printf '%s\n' "$removed" | _lanes_gc_json),\"shm_used_mb\":$(( $(shm_used_kb) / 1024 ))"
  fi
  _lanes_gc_report
  _lanes_gc_report_containers
  return 0
}
# Historical deployment comment omitted from synthetic fixture.
# Historical deployment comment omitted from synthetic fixture.
# Historical deployment comment omitted from synthetic fixture.
# Historical deployment comment omitted from synthetic fixture.
# Historical deployment comment omitted from synthetic fixture.
# Historical deployment comment omitted from synthetic fixture.
lanes_lockcheck() {
  local tree=$1 L f d n_uv=0 n_npm=0 bad=0 t0 out; t0=$(date +%s)
  git -C "$tree" rev-parse --git-dir >/dev/null 2>&1 || { echo "LOCKCHECK failed: $tree is not a git checkout"; return 2; }
  command -v uv >/dev/null 2>&1 || { echo "LOCKCHECK failed: uv is not on PATH"; return 2; }
  command -v npm >/dev/null 2>&1 || { echo "LOCKCHECK failed: npm is not on PATH"; return 2; }
  L=$(mktemp -d "$LANES_JOBS_ROOT/${LANES_WHO:-unspecified}-lockcheck.XXXXXX" 2>/dev/null) || L=$(mktemp -d) || { echo "LOCKCHECK failed: no scratch dir"; return 2; }
  ( cd "$tree" && git ls-files -z | tar --null --ignore-failed-read -T - -cf - 2>/dev/null ) | tar -x -C "$L" 2>/dev/null
  while IFS= read -r -d '' f; do
    f=${f#./}; d=$(dirname "$f"); n_uv=$(( n_uv + 1 ))
    out=$( cd "$L/$d" && timeout 120 uv lock --check 2>&1 ) || { bad=1; echo "LOCKCHECK FAIL $f: $(printf '%s' "$out" | tr '
' ' ' | cut -c1-300)"; }
    git -C "$tree" diff --quiet HEAD -- "$f" 2>/dev/null || echo "LOCKCHECK WARN $f differs from HEAD (uncommitted lock change; CI sees the committed one)"
  done < <(cd "$L" && find . -name uv.lock -not -path '*/node_modules/*' -not -path '*/.venv/*' -print0)
  while IFS= read -r -d '' f; do
    f=${f#./}; d=$(dirname "$f"); n_npm=$(( n_npm + 1 ))
    out=$( cd "$L/$d" && timeout 180 npm ci --dry-run --ignore-scripts --no-audit --no-fund 2>&1 ) || { bad=1; echo "LOCKCHECK FAIL $f: $(printf '%s' "$out" | tr '
' ' ' | cut -c1-300)"; }
    git -C "$tree" diff --quiet HEAD -- "$f" 2>/dev/null || echo "LOCKCHECK WARN $f differs from HEAD (uncommitted lock change; CI sees the committed one)"
  done < <(cd "$L" && find . -name package-lock.json -not -path '*/node_modules/*' -print0)
  case "$L" in "$LANES_JOBS_ROOT"/*|/tmp/*) rm -rf "$L" ;; esac
  [ "$bad" = 0 ] && echo "LOCKCHECK ok: $n_uv uv projects, $n_npm npm projects, $(( $(date +%s) - t0 )) s" || echo "LOCKCHECK failed: $n_uv uv projects, $n_npm npm projects, $(( $(date +%s) - t0 )) s"
  return $bad
}
# Historical deployment comment omitted from synthetic fixture.
LANES_PG_ARGS="--rm --cpus=1.5 --tmpfs /var/lib/postgresql/data:rw,size=256m"
LANES_PG_CMD="-c fsync=off -c synchronous_commit=off -c full_page_writes=off"
# Historical deployment comment omitted from synthetic fixture.
# Historical deployment comment omitted from synthetic fixture.
# Historical deployment comment omitted from synthetic fixture.
LANES_BROWSER_ARGS="--memory 3g --memory-swap 3g --tmpfs /tmp:rw,exec,size=2g -e NODE_OPTIONS=$NODE_OPTIONS"
