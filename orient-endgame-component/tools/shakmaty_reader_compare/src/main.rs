//! Standalone comparison client. No engine search, training or online service.
//! Public native reader stacks are compared; this is not a pure decoder test.
use shakmaty::{CastlingMode, Chess, Move, Position, Role, fen::Fen, uci::UciMove};
use shakmaty_syzygy::{Dtz, MaybeRounded, Tablebase};
use std::{env, fs, io::{self, Write}, process, time::Instant};

const SUCCESS: u8 = 0;
const UNSUPPORTED: u8 = 1;
const UNAVAILABLE: u8 = 2;
const FNV_OFFSET: u64 = 1_469_598_103_934_665_603;
const FNV_PRIME: u64 = 1_099_511_628_211;

#[derive(Clone, Copy, PartialEq)]
enum Mode { Wdl, Dtz, AllMoves, Verify }
impl Mode {
    fn parse(s: &str) -> Result<Self, String> {
        match s {
            "wdl" => Ok(Self::Wdl), "dtz" => Ok(Self::Dtz),
            "all_moves" => Ok(Self::AllMoves), "verify" => Ok(Self::Verify),
            _ => Err("mode must be wdl|dtz|all_moves|verify".to_owned()),
        }
    }
}

struct Input { line: usize, fen: String, position: Result<Chess, String>, terminal_wdl: Option<u8> }
#[derive(Clone, Debug)]
struct Alternative { uci: [u8; 5], len: usize, code: u32, wdl: u8, dtz: u32, rounded: bool }
impl Alternative {
    fn uci_string(&self) -> String { String::from_utf8(self.uci[..self.len].to_vec()).expect("ASCII UCI") }
}
#[derive(Debug)]
struct Value {
    status: u8, wdl: u8, signed_dtz: i32, rounded: bool,
    alternatives: Vec<Alternative>, error: Option<String>,
}
impl Value {
    fn empty(status: u8) -> Self {
        Self { status, wdl: 2, signed_dtz: 0, rounded: false, alternatives: Vec::new(), error: None }
    }
    fn unavailable(error: impl ToString) -> Self {
        let mut out = Self::empty(UNAVAILABLE); out.error = Some(error.to_string()); out
    }
}

fn eligible(pos: &Chess) -> bool { pos.board().occupied().count() <= 5 && !pos.castles().any() }
fn unpack(dtz: MaybeRounded<Dtz>) -> (i32, bool) {
    match dtz { MaybeRounded::Precise(Dtz(n)) => (n, false), MaybeRounded::Rounded(Dtz(n)) => (n, true) }
}
fn nominal_wdl(halfmoves: u32, dtz: i32) -> u8 {
    if dtz > 0 { if dtz as u64 + halfmoves as u64 <= 100 { 4 } else { 3 } }
    else if dtz < 0 { if dtz.unsigned_abs() as u64 + halfmoves as u64 <= 100 { 0 } else { 1 } }
    else { 2 }
}
fn before_zeroing(wdl: i32) -> i32 {
    match wdl { -2 => -1, -1 => -101, 0 => 0, 1 => 101, 2 => 1, _ => unreachable!("five-valued WDL") }
}
fn add_ply(dtz: i32) -> i32 { dtz + dtz.signum() }
fn encode_move(m: Move) -> ([u8; 5], usize, u32) {
    let UciMove::Normal { from, to, promotion } = m.to_uci(CastlingMode::Standard) else {
        unreachable!("standard legal moves with castling excluded")
    };
    let f = from as u32; let t = to as u32;
    let (suffix, promotion_code) = match promotion {
        None => (0, 0), Some(Role::Queen) => (b'q', 1), Some(Role::Rook) => (b'r', 2),
        Some(Role::Bishop) => (b'b', 3), Some(Role::Knight) => (b'n', 4),
        _ => unreachable!("legal promotion type"),
    };
    ([b'a' + (f & 7) as u8, b'1' + (f >> 3) as u8,
      b'a' + (t & 7) as u8, b'1' + (t >> 3) as u8, suffix],
     if suffix == 0 { 4 } else { 5 }, f | (t << 6) | (promotion_code << 12))
}

fn probe_wdl(tables: &Tablebase<Chess>, pos: &Chess) -> Value {
    if !eligible(pos) || pos.halfmoves() != 0 { return Value::empty(UNSUPPORTED); }
    match tables.probe_wdl_after_zeroing(pos) {
        Ok(wdl) => { let mut out = Value::empty(SUCCESS); out.wdl = (wdl as i32 + 2) as u8; out }
        Err(e) => Value::unavailable(e),
    }
}
fn native_dtz(tables: &Tablebase<Chess>, pos: &Chess) -> Value {
    let (dtz, rounded) = match tables.probe_dtz(pos) { Ok(v) => unpack(v), Err(e) => return Value::unavailable(e) };
    Value { status: SUCCESS, wdl: nominal_wdl(pos.halfmoves(), dtz),
        signed_dtz: dtz, rounded, alternatives: Vec::new(), error: None }
}
fn terminal_value(wdl: u8) -> Value { let mut out = Value::empty(SUCCESS); out.wdl = wdl; out }
fn probe_dtz(tables: &Tablebase<Chess>, pos: &Chess, terminal_wdl: Option<u8>) -> Value {
    if !eligible(pos) || pos.halfmoves() >= 100 { return Value::empty(UNSUPPORTED); }
    // Classification is prepared with the fixture in both implementations,
    // outside primitive-DTZ timing. Only mate and stalemate are normalized.
    if let Some(wdl) = terminal_wdl { return terminal_value(wdl); }
    native_dtz(tables, pos)
}
fn probe_root(tables: &Tablebase<Chess>, pos: &Chess) -> Value {
    if !eligible(pos) || pos.halfmoves() >= 100 { return Value::empty(UNSUPPORTED); }
    let legal = pos.legal_moves();
    // Match Orient's complete-root envelope, not the raw DTZ mate convention.
    if legal.is_empty() {
        return terminal_value(if pos.is_check() { 0 } else { 2 });
    }
    let mut out = native_dtz(tables, pos);
    if out.status != SUCCESS { return out; }
    let dtz = out.signed_dtz;
    out.alternatives.reserve(legal.len());
    for m in legal {
        let mut child = pos.clone(); child.play_unchecked(m);
        let (v, child_rounded) = if dtz > 0 && child.is_checkmate() {
            (1, false)
        } else if child.halfmoves() == 0 {
            match tables.probe_wdl_after_zeroing(&child) {
                Ok(wdl) => (before_zeroing(-(wdl as i32)), false), Err(e) => return Value::unavailable(e),
            }
        } else {
            match tables.probe_dtz(&child) {
                Ok(value) => { let (n, r) = unpack(value); (add_ply(-n), r) },
                Err(e) => return Value::unavailable(e),
            }
        };
        let (uci, len, code) = encode_move(m);
        out.alternatives.push(Alternative { uci, len, code, wdl: nominal_wdl(pos.halfmoves(), v), dtz: v.unsigned_abs(), rounded: child_rounded });
    }
    // Included in query timing, just as in the C++ canonical envelope.
    out.alternatives.sort_by_key(|m| m.uci);
    out
}
fn probe(mode: Mode, tables: &Tablebase<Chess>, input: &Input) -> Value {
    let pos = input.position.as_ref().expect("validated benchmark fixture");
    match mode { Mode::Wdl => probe_wdl(tables, pos), Mode::Dtz => probe_dtz(tables, pos, input.terminal_wdl),
        Mode::AllMoves => probe_root(tables, pos), Mode::Verify => unreachable!() }
}
fn mix(hash: &mut u64, n: u64) { *hash = (*hash ^ n).wrapping_mul(FNV_PRIME); }
fn hash_value(hash: &mut u64, mode: Mode, value: &Value) {
    mix(hash, value.status as u64);
    if value.status != SUCCESS { return; }
    mix(hash, value.wdl as u64);
    if mode == Mode::Wdl { return; }
    mix(hash, value.signed_dtz.unsigned_abs() as u64);
    if mode == Mode::Dtz { return; }
    mix(hash, value.alternatives.len() as u64);
    for m in &value.alternatives { mix(hash, m.code as u64); mix(hash, m.wdl as u64); mix(hash, m.dtz as u64); }
}

fn usage() -> Result<(f64, i64), String> {
    let mut raw = std::mem::MaybeUninit::<libc::rusage>::zeroed();
    // SAFETY: raw points to writable storage of the exact libc ABI type.
    if unsafe { libc::getrusage(libc::RUSAGE_SELF, raw.as_mut_ptr()) } != 0 { return Err(io::Error::last_os_error().to_string()); }
    // SAFETY: a successful getrusage initialized the full result structure.
    let u = unsafe { raw.assume_init() };
    let cpu = (u.ru_utime.tv_sec + u.ru_stime.tv_sec) as f64 * 1000.0
        + (u.ru_utime.tv_usec + u.ru_stime.tv_usec) as f64 / 1000.0;
    Ok((cpu, u.ru_maxrss as i64))
}
fn quoted(text: &str) -> String {
    let mut out = String::from("\"");
    for c in text.chars() {
        match c { '"' => out.push_str("\\\""), '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"), '\r' => out.push_str("\\r"), '\t' => out.push_str("\\t"),
            c if c < '\u{20}' => out.push_str(&format!("\\u{:04x}", c as u32)), c => out.push(c) }
    }
    out.push('"'); out
}
fn opt_quoted(text: Option<&str>) -> String { text.map(quoted).unwrap_or_else(|| "null".to_owned()) }
fn verify_line(tables: &Tablebase<Chess>, input: &Input) -> String {
    let Ok(pos) = &input.position else {
        return format!("{{\"line\":{},\"fen\":{},\"parse_ok\":false,\"parse_error\":{},\"status\":1,\"wdl\":2,\"dtz_status\":1,\"signed_dtz\":0,\"nominal_wdl\":2,\"dtz\":0,\"root_status\":1,\"root_wdl\":2,\"root_dtz\":0,\"suggested\":\"0000\",\"moves\":[]}}", input.line, quoted(&input.fen), quoted(input.position.as_ref().err().unwrap()));
    };
    let w = probe_wdl(tables, pos); let d = probe_dtz(tables, pos, input.terminal_wdl); let a = probe_root(tables, pos);
    let mut suggested = "0000".to_owned(); let mut suggested_child_dtz = 0; let mut recommendation_error = None;
    // Diagnostic only. Native best_move does less work than a complete move list
    // and returns child DTZ, so it is never part of the timed/hash contract.
    if a.status == SUCCESS && !a.alternatives.is_empty() {
        match tables.best_move(pos) {
            Ok(Some((m, value))) => { suggested = m.to_uci(CastlingMode::Standard).to_string(); suggested_child_dtz = unpack(value).0; },
            Ok(None) => recommendation_error = Some("native best_move unexpectedly returned none".to_owned()),
            Err(e) => recommendation_error = Some(e.to_string()),
        }
    }
    let moves = a.alternatives.iter().map(|m| format!("[{},{},{}]", quoted(&m.uci_string()), m.wdl, m.dtz)).collect::<Vec<_>>().join(",");
    let rounding = a.alternatives.iter().map(|m| format!("[{},{}]", quoted(&m.uci_string()), m.rounded)).collect::<Vec<_>>().join(",");
    format!("{{\"line\":{},\"fen\":{},\"parse_ok\":true,\"parse_error\":null,\"status\":{},\"wdl\":{},\"dtz_status\":{},\"signed_dtz\":{},\"nominal_wdl\":{},\"dtz\":{},\"root_status\":{},\"root_wdl\":{},\"root_dtz\":{},\"suggested\":{},\"moves\":[{}],\"dtz_rounded\":{},\"root_rounded\":{},\"move_rounding\":[{}],\"suggested_child_dtz\":{},\"recommendation_error\":{},\"wdl_error\":{},\"dtz_error\":{},\"root_error\":{}}}",
        input.line, quoted(&input.fen), w.status, w.wdl, d.status, d.signed_dtz, d.wdl, d.signed_dtz.unsigned_abs(), a.status, a.wdl, a.signed_dtz.unsigned_abs(), quoted(&suggested), moves,
        d.rounded, a.rounded, rounding, suggested_child_dtz, opt_quoted(recommendation_error.as_deref()), opt_quoted(w.error.as_deref()), opt_quoted(d.error.as_deref()), opt_quoted(a.error.as_deref()))
}

fn run() -> Result<(), String> {
    let args = env::args().collect::<Vec<_>>();
    if args.len() != 6 { return Err("usage: BINARY TABLEPATH CORPUS MODE REPEATS BACKEND(mmap|pread)".to_owned()); }
    let mode = Mode::parse(&args[3])?;
    let repeats: usize = args[4].parse().map_err(|_| "invalid repeats")?;
    if !(1..=100).contains(&repeats) { return Err("repeats must be 1..100".to_owned()); }
    let content = fs::read_to_string(&args[2]).map_err(|e| e.to_string())?;
    let inputs = content.lines().filter(|s| !s.is_empty()).enumerate().map(|(index,s)| {
        let position = s.parse::<Fen>().map_err(|e| e.to_string()).and_then(|f| f.into_position::<Chess>(CastlingMode::Standard).map_err(|e| e.to_string()));
        let terminal_wdl = position.as_ref().ok().and_then(|p| p.legal_moves().is_empty().then(|| if p.is_check() { 0 } else { 2 }));
        Input { line: index+1, fen: s.to_owned(), position, terminal_wdl }
    }).collect::<Vec<_>>();
    if inputs.is_empty() { return Err("empty corpus".to_owned()); }
    let start = Instant::now();
    let mut tables: Tablebase<Chess> = match args[5].as_str() {
        // SAFETY: this benchmark's controller verifies an immutable local Syzygy
        // collection, and forbids mutation throughout every invocation. As with
        // the Fathom mmap baseline, I/O faults retain OS mapping consequences.
        "mmap" => unsafe { Tablebase::with_mmap_filesystem() },
        "pread" => Tablebase::new(), _ => return Err("backend must be mmap|pread".to_owned()),
    };
    let table_files = tables.add_directory(&args[1]).map_err(|e| e.to_string())?;
    if tables.max_pieces() != 5 { return Err("complete five-piece collection required".to_owned()); }
    let startup_ms = start.elapsed().as_secs_f64() * 1000.0;
    let rss_before_probes_kib = usage()?.1;
    if mode == Mode::Verify {
        let stdout = io::stdout(); let mut stream = io::BufWriter::new(stdout.lock());
        for input in &inputs { writeln!(stream, "{}", verify_line(&tables, input)).map_err(|e| e.to_string())?; }
        return stream.flush().map_err(|e| e.to_string());
    }
    for input in &inputs { if let Err(e) = &input.position { return Err(format!("invalid benchmark FEN {}: {}", input.fen, e)); } }
    let mut first_hash = FNV_OFFSET;
    let first_start = Instant::now(); let first_cpu_start = usage()?.0;
    for input in &inputs {
        let value = probe(mode, &tables, input);
        if value.status != SUCCESS { return Err(format!("non-success first-pass probe {}: {:?}", input.fen, value)); }
        hash_value(&mut first_hash, mode, &value);
    }
    let first_pass_ms = first_start.elapsed().as_secs_f64() * 1000.0;
    let first_pass_cpu_ms = usage()?.0 - first_cpu_start;
    let calls = inputs.len().checked_mul(repeats).ok_or("call count overflow")?;
    let mut latencies = Vec::with_capacity(calls); let mut semantic_hash = FNV_OFFSET;
    let start = Instant::now(); let cpu_start = usage()?.0;
    for _ in 0..repeats { for input in &inputs {
        let begin = Instant::now(); let value = probe(mode, &tables, input);
        latencies.push(begin.elapsed().as_nanos() as u64);
        if value.status != SUCCESS { return Err(format!("non-success timed probe {}: {:?}", input.fen, value)); }
        hash_value(&mut semantic_hash, mode, &value);
    } }
    let wall_ms = start.elapsed().as_secs_f64() * 1000.0; let (cpu_end, peak_rss_kib) = usage()?;
    latencies.sort_unstable();
    let percentile = |p: usize| latencies[(latencies.len() - 1) * p / 100] as f64 / 1000.0;
    println!("{{\"mode\":{},\"backend\":{},\"positions\":{},\"repeats\":{},\"calls\":{},\"semantic_hash\":\"{}\",\"first_pass_hash\":\"{}\",\"wall_ms\":{:.9},\"cpu_ms\":{:.9},\"p50_us\":{:.9},\"p95_us\":{:.9},\"startup_ms\":{:.9},\"first_pass_ms\":{:.9},\"first_pass_cpu_ms\":{:.9},\"peak_rss_kib\":{},\"rss_before_probes_kib\":{},\"table_files\":{},\"profiling_enabled\":false}}",
        quoted(&args[3]), quoted(&args[5]), inputs.len(), repeats, calls, semantic_hash, first_hash, wall_ms, cpu_end-cpu_start, percentile(50), percentile(95), startup_ms,
        first_pass_ms, first_pass_cpu_ms, peak_rss_kib, rss_before_probes_kib, table_files);
    Ok(())
}
fn main() { if let Err(error) = run() { eprintln!("{}", error); process::exit(1); } }

#[cfg(test)]
mod tests {
    use super::*;
    #[test] fn wdl_boundaries_and_clock() {
        assert_eq!(nominal_wdl(99,1),4); assert_eq!(nominal_wdl(99,2),3);
        assert_eq!(nominal_wdl(99,-1),0); assert_eq!(nominal_wdl(99,-2),1); assert_eq!(nominal_wdl(99,0),2);
        for w in -2..=2 { assert_eq!(nominal_wdl(0,before_zeroing(w)),(w+2) as u8); }
        assert_eq!(add_ply(-101),-102); assert_eq!(add_ply(101),102); assert_eq!(add_ply(0),0);
    }
    #[test] fn canonical_promotion_order_and_codes() {
        let p: Chess = "4k3/6P1/8/8/8/8/8/4K3 w - - 0 1".parse::<Fen>().unwrap().into_position(CastlingMode::Standard).unwrap();
        let mut moves = p.legal_moves().into_iter().filter(|m| m.is_promotion()).map(encode_move).collect::<Vec<_>>();
        moves.sort_by_key(|m|m.0);
        assert_eq!(moves.iter().map(|m|m.0[4]).collect::<Vec<_>>(),b"bnqr");
        for (bytes,_,code) in moves { assert_eq!(code & 63,54); assert_eq!((code>>6)&63,62); assert_eq!(bytes[0],b'g'); }
    }
    #[test] fn quote_control_bytes() { assert_eq!(quoted("a\"\\\n"),"\"a\\\"\\\\\\n\""); }
    #[test] fn unsupported_and_terminal_without_tables() {
        let t=Tablebase::<Chess>::new();
        let mate: Chess="7k/6Q1/6K1/8/8/8/8/8 b - - 0 1".parse::<Fen>().unwrap().into_position(CastlingMode::Standard).unwrap();
        let v=probe_root(&t,&mate); assert_eq!(v.status,SUCCESS); assert_eq!(v.wdl,0); assert_eq!(v.signed_dtz,0); assert!(v.alternatives.is_empty());
        let unsupported: Chess="4k3/8/8/8/8/8/8/4K2R w K - 0 1".parse::<Fen>().unwrap().into_position(CastlingMode::Standard).unwrap();
        assert_eq!(probe_root(&t,&unsupported).status,UNSUPPORTED);
    }
}
