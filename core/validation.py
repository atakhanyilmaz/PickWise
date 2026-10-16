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
