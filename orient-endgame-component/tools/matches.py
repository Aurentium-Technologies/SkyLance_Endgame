#!/usr/bin/env python3
"""Run capped development SPRTs or a frozen fixed-size certification gauntlet."""
import argparse
import os
from pathlib import Path
import re
import signal
import shutil
import subprocess
import threading

from sprt import paired_sprt

from experiment import (ExperimentError, artifact, cli_main, epd_text, metadata, read_epd,
                        read_json, sha256, utc_now, validate_manifest, verify_artifact, write_json, compute_lease,
                        verify_original_network, compute_child_fds)

LOADED_SOURCES = {name: sha256(Path(__file__).with_name(filename)) for name, filename in
                  (("controller", "matches.py"), ("statistics", "experiment.py"), ("calculator", "sprt.py"))}


def original_engine_provenance(engine, checkpoint=None, network_manifest=None):
    checkpoint = checkpoint or str(Path(engine["path"]).parent / "checkpoint.json")
    cp = read_json(checkpoint)
    verify_artifact(cp.get("binary", {}))
    verify_artifact(cp.get("source_archive", {}))
    if cp["binary"]["sha256"] != engine["sha256"]:
        raise ExperimentError("Development engine differs from its frozen source checkpoint")
    engine.update(checkpoint=artifact(checkpoint), source_archive=cp["source_archive"])
    if engine["options"].get("Use NNUE") is True:
        if not network_manifest:
            raise ExperimentError("Neural development engine requires its original network manifest")
        trained = read_json(network_manifest)
        network = trained.get("network", {})
        verify_artifact(network)
        engine.update(network_manifest=artifact(network_manifest), network=network)
        requested = engine["options"].get("EvalFile", network["path"])
        if not isinstance(requested, str) or Path(requested).resolve() != Path(network["path"]).resolve():
            raise ExperimentError("Development EvalFile differs from original training export")
        engine["options"]["EvalFile"] = str(Path(requested).resolve(strict=True))
    elif network_manifest:
        raise ExperimentError("Network manifest supplied while neural evaluation is disabled")
    verify_original_network(engine)


def verify_development_engine(engine):
    for key in (None, "checkpoint", "source_archive"):
        verify_artifact(engine if key is None else engine[key])
    verify_original_network(engine)


def engine_args(engine):
    args = ["-engine", f"cmd={engine['path']}", f"name={engine['name']}", "proto=uci"]
    for key, value in sorted(engine.get("options", {}).items()):
        supported = engine.get("supported_options")
        if supported is not None and key not in supported:
            # Single-threaded engines need not advertise Threads and engines
            # without pondering need not advertise Ponder. The runner never
            # sends go ponder. Other unsupported options are configuration bugs.
            if (key == "Ponder" and value is False) or (key == "Threads" and value == 1):
                continue
            raise ExperimentError(f"{engine['name']} does not advertise option {key}")
        if isinstance(value, bool):
            value = str(value).lower()
        args.append(f"option.{key}={value}")
    return args


def command(runner, first, second, opening, pgn, tc, rounds, sprt=False):
    args = [runner, "-output", "format=cutechess"] + engine_args(first) + engine_args(second)
    args += ["-each", f"tc={tc}", "-openings", f"file={opening}", "format=epd", "order=sequential",
             "-rounds", str(rounds), "-games", "2", "-repeat", "-concurrency", "3", "-maxmoves", "500",
             "-pgnout", f"file={pgn}", "append=false", "notation=san", "nodes=true", "timeleft=true"]
    if sprt:
        args += ["-sprt", "elo0=0", "elo1=5", "alpha=0.05", "beta=0.05", "model=normalized"]
    return args


def run_one(args, path, *, fail_fast=False):
    with Path(path).open("x", encoding="utf-8") as log:
        if fail_fast:
            process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       text=True, bufsize=1, start_new_session=True,
                                       pass_fds=compute_child_fds(),
                                       cwd=Path(path).resolve().parent)
            failed, killer = False, None
            def stop_group(sig):
                try:
                    os.killpg(process.pid, sig)
                except ProcessLookupError:
                    pass
            try:
                for line in process.stdout:
                    log.write(line)
                    log.flush()
                    if not failed and development_runner_failures(line):
                        failed = True
                        log.write("Orient controller: stopping development run after reliability failure\n")
                        log.flush()
                        stop_group(signal.SIGTERM)
                        killer = threading.Timer(5, stop_group, args=(signal.SIGKILL,))
                        killer.daemon = True
                        killer.start()
                code = process.wait()
                return (code or 1) if failed else code
            except BaseException:
                stop_group(signal.SIGKILL)
                process.wait()
                raise
            finally:
                if killer is not None:
                    killer.cancel()
                process.stdout.close()
        run = subprocess.run(args, stdout=log, stderr=subprocess.STDOUT, check=False,
                             pass_fds=compute_child_fds(),
                             cwd=Path(path).resolve().parent)
    return run.returncode


def prepare_out(path):
    path = Path(path).resolve()
    path.mkdir(parents=True, exist_ok=False)
    return path


def verify_sprt_calibration(path):
    """Bind a successful finite calibration to the exact loaded calculator."""
    result = read_json(path)
    if result.get('checks_pass') is not True:
        raise ExperimentError('Paired SPRT calibration did not pass its declared checks')
    for field in ('provenance', 'crosscheck', 'log'):
        verify_artifact(result.get(field, {}))
    provenance = read_json(result['provenance']['path'])
    if (provenance.get('hypotheses_nelo') != [0, 5] or provenance.get('alpha') != .05
            or provenance.get('beta') != .05 or provenance.get('batch_pairs') != 32
            or provenance.get('maximum_games') != 20000):
        raise ExperimentError('Paired SPRT calibration used different test settings')
    verify_artifact(provenance.get('binary', {}))
    sources = provenance.get('sources', {})
    for source in sources.values():
        verify_artifact(source)
    if sources.get('calculator-source.py', {}).get('sha256') != LOADED_SOURCES['calculator']:
        raise ExperimentError('Paired SPRT calibration tested a different calculator source')
    crosscheck = read_json(result['crosscheck']['path'])
    if crosscheck.get('passed') is not True:
        raise ExperimentError('Paired SPRT calculator crosscheck did not pass')
    return artifact(path)


def verify_saved_paired_batch(saved, command_base, positions, offset, count, tc):
    """Bind a recovered complete batch to the same declared schedule/settings."""
    from experiment import parse_pgn
    verify_artifact(saved)
    record = read_json(saved['path'])
    for field in ('command', 'opening', 'log', 'pgn'):
        verify_artifact(record[field])
    if record.get('exit_code') != 0 or record.get('error'):
        raise ExperimentError('Cannot recover a failed batch')
    declared = read_json(record['command']['path'])
    expected = list(command_base)
    expected[expected.index('-openings') + 1] = 'file=' + record['opening']['path']
    expected[expected.index('-pgnout') + 1] = 'file=' + record['pgn']['path']
    expected[expected.index('-rounds') + 1] = str(count)
    if (declared.get('argv') != expected or declared.get('first_global_round') != offset + 1
            or declared.get('fixed_games') != count * 2 or declared.get('opening') != record['opening']):
        raise ExperimentError('Recovered batch command differs from declared schedule/settings')
    if read_epd(record['opening']['path']) != positions:
        raise ExperimentError('Recovered batch opening slice differs')
    text = Path(record['log']['path']).read_text(encoding='utf-8')
    if development_runner_failures(text):
        raise ExperimentError('Recovered batch log fails reliability')
    audit = audit_development_games(parse_pgn(record['pgn']['path']), positions, tc,
                                    maximum_games=count * 2)
    if (audit != record.get('audit') or audit['completed_games'] != count * 2
            or audit['reliability_failures']):
        raise ExperimentError('Recovered batch audit differs or is incomplete')
    return record


def run_paired_sprt(template, path, *, batch_pairs=32, verify_inputs=lambda: None,
                    prior_batches=(), batch_executor=None, verify_batch_details=lambda record: None):
    """Run fixed complete-pair batches; decide only after every batch is audited."""
    from experiment import fen_key, parse_pgn
    stage, path = Path(path).parent, Path(path)
    maximum_pairs = int(template[template.index('-rounds') + 1])
    if not 1 <= maximum_pairs <= 10000 or not 1 <= batch_pairs <= 32:
        raise ExperimentError('Invalid paired SPRT batch size or game cap')
    cutoff = template.index('-sprt')
    if template[cutoff + 1:] != ['elo0=0', 'elo1=5', 'alpha=0.05', 'beta=0.05', 'model=normalized']:
        raise ExperimentError('Paired development test must retain the declared SPRT bounds')
    command_base = template[:cutoff]
    book_arg = command_base.index('-openings') + 1
    pgn_arg = command_base.index('-pgnout') + 1
    tc = command_base[command_base.index('-each') + 1].split('=', 1)[1]
    positions = read_epd(command_base[book_arg].split('=', 1)[1])
    if len(positions) < maximum_pairs or len({fen_key(fen) for fen in positions}) != len(positions):
        raise ExperimentError('Paired SPRT needs a unique opening for every pair up to its declared cap')
    aggregate_pgn = Path(command_base[pgn_arg].split('=', 1)[1])
    if len(prior_batches) * batch_pairs >= maximum_pairs:
        raise ExperimentError('Recovery prefix must leave scheduled games to execute')
    all_scores, batches = [], []
    with path.open('x', encoding='utf-8') as log, aggregate_pgn.open('x', encoding='utf-8') as aggregate:
        for offset in range(0, maximum_pairs, batch_pairs):
            count = min(batch_pairs, maximum_pairs - offset)
            if len(batches) < len(prior_batches):
                verify_inputs()
                saved = prior_batches[len(batches)]
                record = verify_saved_paired_batch(saved, command_base,
                            positions[offset:offset + count], offset, count, tc)
                all_scores.extend(record['audit']['pair_scores'])
                state = paired_sprt(all_scores)
                if state != record.get('cumulative_statistics') or state['verdict'] != 'inconclusive':
                    raise ExperimentError('Recovery prefix statistics differ or already decided the stage')
                raw = Path(record['pgn']['path']).read_text(encoding='utf-8')
                raw = re.sub(r'(?m)^\[Round "([1-9][0-9]*)"\]$',
                             lambda match: f'[Round "{int(match[1]) + offset}"]', raw)
                aggregate.write(raw.rstrip() + '\n\n'); aggregate.flush()
                log.write(f'Recovered complete batch {len(batches) + 1}; {len(all_scores) * 2} games\n')
                log.write(Path(record['log']['path']).read_text(encoding='utf-8'))
                log.flush(); batches.append(saved)
                continue
            batch = stage / f'batch-{len(batches) + 1:04d}'
            batch.mkdir()
            book, pgn, runner_log = batch / 'openings.epd', batch / 'games.pgn', batch / 'runner.log'
            book.write_text(epd_text(positions[offset:offset + count], 'paired-batch'), encoding='utf-8')
            cmd = list(command_base)
            cmd[book_arg] = 'file=' + str(book.resolve())
            cmd[pgn_arg] = 'file=' + str(pgn.resolve())
            cmd[cmd.index('-rounds') + 1] = str(count)
            write_json(batch / 'command.json', {'argv': cmd, 'first_global_round': offset + 1,
                                               'fixed_games': count * 2, 'opening': artifact(book),
                                               'execution': 'direct runner' if batch_executor is None
                                                   else 'delegated; suffix recovery records its actual command separately',
                                               'started_utc': utc_now()})
            verify_inputs()
            details = {}
            if batch_executor is None:
                code = run_one(cmd, runner_log, fail_fast=True)
            else:
                code, details = batch_executor(cmd, runner_log, verify_inputs)
                if set(details) - {'recovery'}:
                    raise ExperimentError('Unexpected recovered execution metadata')
            batch_record = {'exit_code': code, 'command': artifact(batch / 'command.json'),
                            'opening': artifact(book), 'log': artifact(runner_log)}
            batch_record.update(details)
            text = runner_log.read_text(encoding='utf-8')
            log.write(f'Batch {len(batches) + 1}, global pairs {offset + 1}..{offset + count}\n' + text)
            log.flush()
            if pgn.is_file():
                batch_record['pgn'] = artifact(pgn)
            try:
                verify_inputs()
                failures = development_runner_failures(text)
                if code or failures:
                    raise ExperimentError('Fixed batch runner failed reliability: ' + '; '.join(failures))
                verify_batch_details(batch_record)
                audit = audit_development_games(parse_pgn(pgn), positions[offset:offset + count], tc,
                                                maximum_games=count * 2)
                batch_record['audit'] = audit
                if audit['completed_games'] != count * 2 or audit['reliability_failures']:
                    raise ExperimentError('Fixed batch did not finish all declared reliable opening pairs: '
                                          + '; '.join(audit['reliability_failures']))
                all_scores.extend(audit['pair_scores'])
                # Preserve raw batch PGNs, including every move annotation. Only
                # the derived aggregate's Round headers receive the global offset.
                raw = pgn.read_text(encoding='utf-8')
                raw = re.sub(r'(?m)^\[Round "([1-9][0-9]*)"\]$',
                             lambda match: f'[Round "{int(match[1]) + offset}"]', raw)
                aggregate.write(raw.rstrip() + '\n\n'); aggregate.flush()
                state = paired_sprt(all_scores)
                batch_record.update(audit=audit, cumulative_statistics=state, finished_utc=utc_now())
                write_json(batch / 'result.json', batch_record)
                batches.append(artifact(batch / 'result.json'))
                log.write(f"Paired SPRT: {len(all_scores) * 2} games; llr={state['llr']:.9f}; {state['verdict']}\n")
                log.flush()
                print(f"{tc}: {len(all_scores) * 2} paired games; llr={state['llr']:.6f}; {state['verdict']}", flush=True)
                if state['verdict'] != 'inconclusive' or offset + count == maximum_pairs:
                    for saved in batches:
                        verify_artifact(saved)
                        completed = read_json(saved['path'])
                        for key in ('command', 'opening', 'log', 'pgn'):
                            verify_artifact(completed[key])
                    write_json(stage / 'sprt-result.json', state)
                    write_json(stage / 'paired-batches.json', {'batch_pairs': batch_pairs,
                               'maximum_games': maximum_pairs * 2, 'batches': batches,
                               'statistics': artifact(stage / 'sprt-result.json')})
                    if state['verdict'] != 'inconclusive':
                        log.write(('H1' if state['verdict'] == 'accepted' else 'H0') + ' was accepted\n')
                    return 0
            except (ExperimentError, OSError, ValueError, KeyError) as error:
                batch_record.update(error=str(error), finished_utc=utc_now())
                error_path = batch / ('controller-error.json' if (batch / 'result.json').exists() else 'result.json')
                write_json(error_path, batch_record)
                log.write('Paired controller evidence failure: ' + str(error) + '\n'); log.flush()
                return 1
    return 1


def run_pilot(args):
    """A small gap/reliability measurement, never a certification campaign."""
    if type(args.games) is not int or not 2 <= args.games <= 1000 or args.games % 2:
        raise ExperimentError("Pilot --games must be even and between 2 and 1000")
    tc = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)\+([0-9]+(?:\.[0-9]+)?)", args.tc)
    if not tc or not 0 < float(tc[1]) <= 120 or not 0 <= float(tc[2]) <= 1:
        raise ExperimentError("Pilot --tc must be seconds+increment, at most 120+1")
    if not args.opponent_name.strip() or args.opponent_name == "Orient":
        raise ExperimentError("Pilot opponent needs a distinct nonempty name")
    positions = read_epd(args.openings)
    if len(positions) < args.games // 2:
        raise ExperimentError("Pilot needs one unique opening for each reversed game pair")
    from freeze import probe_uci
    engines = []
    for path, name, overrides in ((args.candidate, "Orient", args.candidate_option),
                                  (args.opponent, args.opponent_name, args.baseline_option)):
        engine = dict(artifact(path), name=name, options={"Threads": 1, "Hash": 64, "Ponder": False})
        engine["options"].update(parse_options(overrides))
        engine["uci_probe"] = probe_uci(engine["path"])
        engine["supported_options"] = engine["uci_probe"]["supported_options"]
        engine_args(engine)
        engines.append(engine)
    checkpoint = getattr(args, "candidate_checkpoint", None)
    if checkpoint is None:
        sibling = Path(engines[0]["path"]).parent / "checkpoint.json"
        if sibling.is_file():
            checkpoint = str(sibling)
    if checkpoint:
        cp = read_json(checkpoint)
        verify_artifact(cp.get("binary", {}))
        verify_artifact(cp.get("source_archive", {}))
        if cp["binary"]["sha256"] != engines[0]["sha256"]:
            raise ExperimentError("Pilot candidate does not match its source checkpoint")
        engines[0]["checkpoint"] = artifact(checkpoint)
        engines[0]["source_archive"] = cp["source_archive"]
    else:
        engines[0]["source_provenance"] = "No source checkpoint supplied; development pilot only"
    if engines[0]["options"].get("Use NNUE") is True:
        original_engine_provenance(engines[0], checkpoint, getattr(args, "candidate_network_manifest", None))
    out = prepare_out(args.out)
    book, pgn, log = out / "openings.epd", out / "games.pgn", out / "runner.log"
    positions = positions[:args.games // 2]
    book.write_text(epd_text(positions, "pilot"), encoding="utf-8")
    record = {"kind": "pilot", "label": "Development pilot: score and reliability only; no rating certification",
              "metadata": metadata(), "candidate": engines[0], "opponent": engines[1],
              "fastchess": artifact(args.fastchess), "input_openings": artifact(args.openings),
              "openings": artifact(book), "requested_games": args.games, "time_control": args.tc,
              "concurrency": 3, "generator": artifact(__file__), "statistical_tools": artifact(Path(__file__).with_name("experiment.py")),
              "started_utc": utc_now(), "certification": False}
    write_json(out / "provenance.json", record)
    cmd = command(record["fastchess"]["path"], *engines, str(book), str(pgn), args.tc, args.games // 2)
    write_json(out / "command.json", {"argv": cmd, "opening": artifact(book), "fixed_games": args.games,
                                      "time_control": args.tc, "started_utc": utc_now()})
    print(f"Starting {args.games}-game development pilot against {args.opponent_name} at {args.tc}", flush=True)
    code = run_one(cmd, log)
    result = {"kind": "pilot", "label": record["label"], "certification": False,
              "provenance": artifact(out / "provenance.json"), "command": artifact(out / "command.json"),
              "exit_code": code, "finished_utc": utc_now(), "log": artifact(log),
              "requested_games": args.games, "completed_games": 0, "complete": False,
              "reliability_pass": False}
    if pgn.is_file():
        result["pgn"] = artifact(pgn)
        try:
            from experiment import parse_pgn, collect_pairs
            games = parse_pgn(pgn)
            result["completed_games"] = len(games)
            pairs, wdl, failures = collect_pairs(games, "Orient", args.opponent_name, positions)
            result.update(opening_pairs=len(pairs), wins=wdl[0], draws=wdl[1], losses=wdl[2],
                          pair_scores=pairs, points=sum(pairs), score=sum(pairs) / len(games) if games else 0,
                          complete=code == 0 and len(games) == args.games)
            diagnostics = log.read_text(encoding="utf-8")
            failures += re.findall(r"(?im)^.*(?:illegal move|connection stalls|engine crashed|disconnect|loses on time|time forfeit|time limit exceeded|runtime error|fatal error).*$", diagnostics)
            result["reliability_failures"] = failures
            result["reliability_pass"] = result["complete"] and not failures
        except ExperimentError as error:
            result["audit_error"] = str(error)
    else:
        result["audit_error"] = "Runner did not write a PGN"
    # Detect binary mutation while the match was in flight.
    for index, engine in enumerate(engines):
        try:
            verify_artifact(engine)
            if index == 0 and "checkpoint" in engine:
                verify_development_engine(engine)
        except ExperimentError as error:
            result["artifact_error"] = str(error)
            result["reliability_pass"] = False
    write_json(out / "result.json", result)
    if "wins" in result:
        print(f"Pilot W-D-L: {result['wins']}-{result['draws']}-{result['losses']}; score {100 * result['score']:.1f}%; complete={result['complete']}; reliability={result['reliability_pass']}", flush=True)
    print(f"Pilot evidence: {out}; no Elo certification is inferred", flush=True)
    if not result["reliability_pass"]:
        raise SystemExit(1)


def run_dev(args):
    calibration_path = getattr(args, 'sprt_calibration', None)
    calibration = verify_sprt_calibration(calibration_path) if calibration_path else None
    engines = [dict(artifact(path), name=name,
                   options={"Threads": 1, "Hash": 64, "Ponder": False})
               for path, name in ((args.candidate, "candidate"), (args.baseline, "baseline"))]
    engines[0]["options"].update(parse_options(args.candidate_option))
    engines[1]["options"].update(parse_options(args.baseline_option))
    from freeze import probe_uci
    for engine, prefix in zip(engines, ("candidate", "baseline")):
        original_engine_provenance(engine, getattr(args, prefix + "_checkpoint", None),
                                   getattr(args, prefix + "_network_manifest", None))
        engine["uci_probe"] = probe_uci(engine["path"])
        engine["supported_options"] = engine["uci_probe"]["supported_options"]
        engine_args(engine)
    development = read_epd(args.development)
    confirmation = read_epd(args.confirmation)
    from experiment import fen_key
    if not development or not confirmation:
        raise ExperimentError("Development and confirmation books must be nonempty")
    if {fen_key(fen) for fen in development} & {fen_key(fen) for fen in confirmation}:
        raise ExperimentError("Development and confirmation openings overlap")
    opening_records = [artifact(args.development), artifact(args.confirmation)]
    out = prepare_out(args.out)
    shutil.copy2(__file__, out / "controller-source.py")
    shutil.copy2(Path(__file__).with_name("experiment.py"), out / "statistics-source.py")
    shutil.copy2(Path(__file__).with_name("sprt.py"), out / "calculator-source.py")
    for name in ('controller', 'statistics', 'calculator'):
        if sha256(out / (name + '-source.py')) != LOADED_SOURCES[name]:
            raise ExperimentError('Loaded research source changed before freezing: ' + name)
    record = {"kind": "development", "metadata": metadata(), "candidate": engines[0],
              "baseline": engines[1], "fastchess": artifact(args.fastchess),
              "controller": artifact(out / "controller-source.py"),
              "statistics": artifact(out / "statistics-source.py"),
              "calculator": artifact(out / "calculator-source.py"),
              "sprt_protocol": {"unit": "complete opening pair", "batch_pairs": 32,
                                "elo0": 0, "elo1": 5, "alpha": .05, "beta": .05,
                                "maximum_games_per_stage": 20000},
              "opening_corpora": dict(zip(("development", "confirmation"), opening_records)),
              "engine_settings": engines, "stages": []}
    if calibration is not None:
        record['sprt_calibration'] = calibration
    write_json(out / "provenance.json", record)
    for index, (book, tc, positions) in enumerate(((args.development, "10+0.1", development),
                                                  (args.confirmation, "60+0.6", confirmation))):
        stage = out / f"stage-{index + 1}"
        stage.mkdir()
        cmd = command(str(Path(args.fastchess).resolve(strict=True)), *engines,
                      str(Path(book).resolve()), str(stage / "games.pgn"), tc, 10000, sprt=True)
        opening = opening_records[index]
        write_json(stage / "command.json", {"template_argv": cmd, "execution": "fixed complete-pair batches; commands saved in batch directories",
                                           "opening": opening, "time_control": tc,
                                           "maximum_games": 20000, "started_utc": utc_now()})
        stage_result = {"time_control": tc, "exit_code": None, "verdict": "runner_failed",
                        "command": artifact(stage / "command.json"), "opening": opening,
                        "reliability_failures": []}
        try:
            for engine in engines:
                verify_development_engine(engine)
            verify_artifact(record["fastchess"])
            for frozen_book in opening_records:
                verify_artifact(frozen_book)
            for field in ("command", "opening", "log", "pgn"):
                if field in stage_result:
                    verify_artifact(stage_result[field])
            for field in ("controller", "statistics", "calculator"):
                verify_artifact(record[field])
        except ExperimentError as error:
            stage_result.update(verdict="artifact_changed", artifact_error=str(error))
        else:
            try:
                def verify_batch_inputs():
                    for engine in engines:
                        verify_development_engine(engine)
                    verify_artifact(record['fastchess'])
                    for frozen_book in opening_records:
                        verify_artifact(frozen_book)
                    for field in ('controller', 'statistics', 'calculator'):
                        verify_artifact(record[field])
                    if calibration is not None:
                        verify_artifact(calibration)
                        verify_sprt_calibration(calibration['path'])
                    verify_artifact(stage_result['command'])
                stage_result["exit_code"] = run_paired_sprt(cmd, stage / "runner.log", verify_inputs=verify_batch_inputs)
            except KeyboardInterrupt:
                stage_result.update(exit_code=130, runner_error="Tournament controller interrupted")
            except (OSError, subprocess.SubprocessError, ExperimentError) as error:
                stage_result["runner_error"] = str(error)
            log = stage / "runner.log"
            text = log.read_text(encoding="utf-8") if log.is_file() else ""
            if log.is_file():
                stage_result["log"] = artifact(log)
            stage_result["reliability_failures"] = development_runner_failures(text)
            accepted = bool(re.search(r"H1\s+was\s+accepted", text))
            rejected = bool(re.search(r"H0\s+was\s+accepted", text))
            verdict = "accepted" if accepted else "rejected" if rejected else "inconclusive"
            if accepted and rejected:
                verdict = "evidence_failed"
                stage_result["audit_error"] = "Runner reports conflicting SPRT decisions"
            if stage_result["exit_code"] != 0 or "runner_error" in stage_result:
                verdict = "runner_failed"
            pgn = stage / "games.pgn"
            if pgn.is_file():
                stage_result["pgn"] = artifact(pgn)
                try:
                    from experiment import parse_pgn
                    games = parse_pgn(pgn)
                    stage_result["completed_games"] = len(games)
                    audit = audit_development_games(games, positions, tc)
                    stage_result["reliability_failures"] += audit.pop("reliability_failures")
                    stage_result.update(audit)
                    if stage_result['exit_code'] == 0 and not stage_result['reliability_failures'] and verdict in ('accepted', 'rejected', 'inconclusive'):
                        calculated = paired_sprt(stage_result['pair_scores'])
                        recorded = read_json(stage / 'sprt-result.json')
                        if recorded != calculated or recorded['verdict'] != verdict:
                            raise ExperimentError('Paired SPRT decision disagrees with the complete audited game pairs')
                        stage_result['sprt'] = artifact(stage / 'sprt-result.json')
                        stage_result['paired_batches'] = artifact(stage / 'paired-batches.json')
                except (ExperimentError, OSError, ValueError, KeyError) as error:
                    stage_result["audit_error"] = str(error)
                    verdict = "evidence_failed"
            else:
                verdict = "missing_pgn"
                stage_result["audit_error"] = "Runner did not write a PGN"
            if stage_result["reliability_failures"]:
                verdict = "reliability_failed"
            stage_result["verdict"] = verdict
        try:
            for engine in engines:
                verify_development_engine(engine)
            verify_artifact(record["fastchess"])
            for frozen_book in opening_records:
                verify_artifact(frozen_book)
            for field in ("command", "opening", "log", "pgn"):
                if field in stage_result:
                    verify_artifact(stage_result[field])
            for field in ("controller", "statistics", "calculator"):
                verify_artifact(record[field])
        except ExperimentError as error:
            stage_result.update(verdict="artifact_changed", artifact_error=str(error))
        verdict = stage_result["verdict"]
        stage_result["finished_utc"] = utc_now()
        record["stages"].append(stage_result)
        write_json(stage / "result.json", record["stages"][-1])
        print(f"{tc}: {verdict}", flush=True)
        if verdict != "accepted":
            break
    record["accepted_both_stages"] = len(record["stages"]) == 2 and all(
        s["verdict"] == "accepted" for s in record["stages"])
    write_json(out / "result.json", record)
    if not record["accepted_both_stages"]:
        raise SystemExit(1)


def development_runner_failures(text):
    """Fatal diagnostics override an apparently successful SPRT line or PGN."""
    return re.findall(
        r"(?im)^.*(?:illegal move|\bcrash(?:ed)?\b|disconnect|connection stalls|engine stalls|"
        r"loses on time|time forfeit|time limit exceeded|timed out|timeout|runtime error|fatal error|"
        r"tournament was interrupted|tournament (?:was )?aborted|tournament (?:was )?stopped).*$", text)


def audit_development_games(games, positions, tc, maximum_games=20000):
    """Audit a contiguous completed round prefix, allowing book wrap and finish reordering.

    Fastchess's sequential opening n is tied to Round n, not PGN write order:
    concurrent games may finish out of order. Each numeric round must still have
    exactly the expected opening in both colours. Resampling/grouping all rounds
    by FEN would incorrectly reject legitimate later cycles through the book.
    """
    from experiment import collect_pairs, fen_key
    if not positions:
        raise ExperimentError("No frozen development openings")
    if not 2 <= len(games) <= maximum_games or len(games) % 2:
        raise ExperimentError("Development evidence needs 2–20000 completed games in complete pairs")
    rounds = {}
    for game in games:
        round_tag = game.get("Round", "")
        if not isinstance(round_tag, str) or re.fullmatch(r"[1-9][0-9]*", round_tag) is None:
            raise ExperimentError("Development PGN requires a positive numeric Round tag")
        number = int(round_tag)
        if number > maximum_games // 2:
            raise ExperimentError("Development Round exceeds declared game cap")
        if "FEN" not in game:
            raise ExperimentError("Development PGN requires its opening FEN")
        expected = positions[(number - 1) % len(positions)]
        if fen_key(game["FEN"]) != fen_key(expected):
            raise ExperimentError(f"Round {number} opening differs from the frozen sequential book")
        if game["FEN"].split()[4:] != expected.split()[4:]:
            raise ExperimentError(f"Round {number} opening clocks differ from the frozen EPD defaults")
        if game.get("TimeControl") != tc:
            raise ExperimentError("Development PGN time control differs from declared stage")
        rounds.setdefault(number, []).append(game)
    if sorted(rounds) != list(range(1, len(rounds) + 1)):
        raise ExperimentError("Development PGN rounds must be a contiguous prefix beginning at 1")
    scores, wins, draws, losses, failures = [], 0, 0, 0, []
    for number, round_games in sorted(rounds.items()):
        if len(round_games) != 2:
            raise ExperimentError(f"Round {number} is missing or duplicates a reversed-colour game")
        pair_scores, wdl, bad = collect_pairs(round_games, "candidate", "baseline",
                                              [positions[(number - 1) % len(positions)]])
        scores.extend(pair_scores)
        wins += wdl[0]
        draws += wdl[1]
        losses += wdl[2]
        failures.extend(f"Round {number}: {detail}" for detail in bad)
    return {"completed_games": len(games), "completed_rounds": len(rounds),
            "wins": wins, "draws": draws, "losses": losses,
            "pair_scores": scores, "reliability_failures": failures}


def run_certify(args):
    manifest = read_json(args.manifest)
    validate_manifest(manifest)
    out = prepare_out(args.out)
    openings = read_epd(manifest["holdout"]["path"])
    provenance = {"kind": "certification", "manifest": artifact(args.manifest),
                  "metadata": metadata(), "runs": []}
    write_json(out / "provenance.json", provenance)
    for i, opponent in enumerate(manifest["opponents"]):
        validate_manifest(manifest)  # Detect modified executables between opponent runs.
        sub = out / f"opponent-{i + 1:02d}"
        sub.mkdir()
        book = sub / "openings.epd"
        book.write_text(epd_text(openings[i * 500:(i + 1) * 500], f"cert-{i + 1}"), encoding="utf-8")
        pgn = sub / "games.pgn"
        cmd = command(manifest["fastchess"]["path"], manifest["candidate"], opponent,
                      str(book), str(pgn), "120+1", 500)
        write_json(sub / "command.json", {"argv": cmd, "opening": artifact(book), "opponent": opponent["name"],
                                         "started_utc": utc_now(), "fixed_games": 1000})
        print(f"Starting fixed 1000-game match against {opponent['name']}", flush=True)
        code = run_one(cmd, sub / "runner.log")
        run = {"opponent": opponent["name"], "directory": str(sub), "exit_code": code,
               "finished_utc": utc_now(), "log": artifact(sub / "runner.log"),
               "command": artifact(sub / "command.json"), "opening": artifact(book)}
        if pgn.is_file():
            run["pgn"] = artifact(pgn)
        write_json(sub / "result.json", run)
        provenance["runs"].append(run)
        if code:
            break
    validate_manifest(manifest)
    provenance["finished_utc"] = utc_now()
    provenance["all_six_completed"] = len(provenance["runs"]) == 6 and all(
        run["exit_code"] == 0 for run in provenance["runs"])
    write_json(out / "runs.json", provenance)
    print(f"Saved campaign evidence to {out}; run tools/rating.py for validation and analysis")
    if not provenance["all_six_completed"]:
        raise SystemExit(1)


def parse_options(values):
    result = {}
    for item in values:
        if "=" not in item:
            raise ExperimentError("Engine option must be NAME=VALUE")
        name, value = item.split("=", 1)
        if not name.strip() or name in result:
            raise ExperimentError("Engine option needs a nonempty unique name")
        if value.casefold() in ("true", "false"):
            value = value.casefold() == "true"
        elif re.fullmatch(r"-?[0-9]+", value):
            value = int(value)
        if name == "Threads" and (type(value) is not int or value != 1):
            raise ExperimentError("Match engines use one search thread")
        if name == "Ponder" and value is not False:
            raise ExperimentError("Pondering must remain disabled")
        result[name] = value
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    pilot = sub.add_parser("pilot", help="Bounded fixed-score development sample; never a rating certificate")
    for key in ("candidate", "opponent", "opponent-name", "openings", "fastchess", "out"):
        pilot.add_argument(f"--{key}", required=True)
    pilot.add_argument("--candidate-checkpoint", help="Defaults to checkpoint.json beside candidate binary")
    pilot.add_argument("--candidate-network-manifest", help="Required when Orient enables Use NNUE")
    pilot.add_argument("--games", type=int, default=64, help="Even count, 2–1000; default 64")
    pilot.add_argument("--tc", default="3+0.03", help="Seconds+increment, at most 120+1")
    pilot.add_argument("--candidate-option", action="append", default=[], metavar="NAME=VALUE")
    pilot.add_argument("--baseline-option", "--opponent-option", action="append", default=[], metavar="NAME=VALUE")
    pilot.set_defaults(function=run_pilot)
    dev = sub.add_parser("dev", help="SPRT [0,5] nElo, max 20000 games per stage; 10+.1 then 60+.6")
    for key in ("candidate", "baseline", "fastchess", "development", "confirmation", "out"):
        dev.add_argument(f"--{key}", required=True)
    dev.add_argument('--sprt-calibration', required=True,
                     help='Successful frozen calibration result for this exact paired calculator')
    dev.add_argument("--candidate-option", action="append", default=[], metavar="NAME=VALUE")
    dev.add_argument("--baseline-option", action="append", default=[], metavar="NAME=VALUE")
    for prefix in ("candidate", "baseline"):
        dev.add_argument(f"--{prefix}-checkpoint", help="Defaults to checkpoint.json beside the frozen original binary")
        dev.add_argument(f"--{prefix}-network-manifest", help="Required when this side enables Use NNUE")
    dev.set_defaults(function=run_dev)
    cert = sub.add_parser("certify", help="Fixed six-opponent, 6000-game, 120+1 campaign")
    cert.add_argument("--manifest", required=True)
    cert.add_argument("--out", required=True)
    cert.set_defaults(function=run_certify)
    args = parser.parse_args()
    with compute_lease("matches:" + args.action + ":" + str(Path(args.out).resolve())):
        args.function(args)


if __name__ == "__main__":
    cli_main(main)
