"""Independent schedule checks: no solver or upstream environment imports."""

from collections import Counter, defaultdict


def validate(jobs, n_machines, rows):
    errors = []
    expected = {(j, o) for j, job in enumerate(jobs) for o in range(len(job))}
    counts = Counter((r["job"], r["operation"]) for r in rows)
    if set(counts) != expected or any(count != 1 for count in counts.values()):
        errors.append("Operation coverage/uniqueness")
    by_op, by_machine = {}, defaultdict(list)
    for row in rows:
        key = row["job"], row["operation"]
        m, start, end = row["machine"], row["start"], row["end"]
        if (
            any(type(v) is not int for v in (m, start, end))
            or start < 0
            or end <= start
        ):
            errors.append(f"Invalid interval: {key}")
            continue
        if key not in expected:
            continue
        options = jobs[key[0]][key[1]]
        if not 0 <= m < n_machines or m not in options:
            errors.append(f"Ineligible machine: {key}")
        elif end - start != options[m]:
            errors.append(f"Wrong duration: {key}")
        by_op[key] = row
        by_machine[m].append(row)
    for j, job in enumerate(jobs):
        for o in range(1, len(job)):
            before, after = by_op.get((j, o - 1)), by_op.get((j, o))
            if before and after and before["end"] > after["start"]:
                errors.append(f"Precedence: {(j, o)}")
    for m, operations in by_machine.items():
        operations.sort(key=lambda row: row["start"])
        for before, after in zip(operations, operations[1:]):
            if before["end"] > after["start"]:
                errors.append(f"Overlap: machine {m}")
    return errors


def validate_workshop(scenario, rows):
    """Validate against original workshop data, independent of solver/env mapping."""
    machine_index = {
        machine.machine_id: i for i, machine in enumerate(scenario.machines)
    }
    jobs = []
    for job in scenario.jobs:
        options = []
        for op in job.operations:
            if op.status == "not_started":
                options.append(
                    {machine_index[m]: d for m, d in op.processing_times.items()}
                )
            else:
                end = (
                    op.fixed_end
                    if op.status == "completed"
                    else scenario.current_time + op.remaining_duration
                )
                options.append(
                    {machine_index[op.fixed_machine_id]: end - op.fixed_start}
                )
        jobs.append(options)
    errors = validate(jobs, len(scenario.machines), rows)
    by_op = {(r["job"], r["operation"]): r for r in rows}
    for j, job in enumerate(scenario.jobs):
        for o, op in enumerate(job.operations):
            row = by_op.get((j, o))
            if row is None:
                continue
            if o == 0 and row["start"] < job.release_time:
                errors.append(f"Release time: {j}")
            if op.status == "not_started":
                if row["start"] < scenario.current_time:
                    errors.append(f"Before current time: {(j, o)}")
            else:
                end = (
                    op.fixed_end
                    if op.status == "completed"
                    else scenario.current_time + op.remaining_duration
                )
                if (row["start"], row["end"], row["machine"]) != (
                    op.fixed_start,
                    end,
                    machine_index[op.fixed_machine_id],
                ):
                    errors.append(f"Frozen operation changed: {(j, o)}")
            if (
                o == len(job.operations) - 1
                and job.deadline is not None
                and row["end"] > job.deadline
            ):
                errors.append(f"Hard deadline: {j}")
            if 0 <= row["machine"] < len(scenario.machines):
                for start, end in scenario.machines[
                    row["machine"]
                ].unavailable_intervals:
                    if row["start"] < end and start < row["end"]:
                        errors.append(f"Downtime overlap: {(j, o)}")
    return errors
