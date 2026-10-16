"""Workshop-specific CP-SAT constraints; upstream benchmark model stays unchanged."""

from collections import defaultdict

from ortools.sat.python import cp_model


def workshop_cp_sat_model(env):
    scenario = env.workshop_scenario
    # A serial schedule can start after every release, fixed end and downtime.
    anchors = [scenario.current_time] + [j.release_time for j in scenario.jobs]
    anchors += [b for m in scenario.machines for _, b in m.unavailable_intervals]
    anchors += [
        op.fixed_end or scenario.current_time
        for j in scenario.jobs
        for op in j.operations
    ]
    horizon = max(anchors) + sum(
        max(op.processing_times.values()) for op in env.operations
    )
    model = cp_model.CpModel()
    starts, presences, intervals, last_ends = {}, {}, defaultdict(list), []
    for j, job in enumerate(env.jobs):
        previous_end = None
        for o, op in enumerate(job.operations):
            source = scenario.jobs[j].operations[o]
            start = model.NewIntVar(0, horizon, f"start_{j}_{o}")
            end = model.NewIntVar(0, horizon, f"end_{j}_{o}")
            starts[j, o] = start
            choices = []
            for a, (m, duration) in enumerate(op.processing_times.items()):
                chosen = model.NewBoolVar(f"choice_{j}_{o}_{a}")
                presences[j, o, a] = chosen
                choices.append(chosen)
                intervals[m].append(
                    model.NewOptionalIntervalVar(
                        start, duration, end, chosen, f"op_{j}_{o}_{a}"
                    )
                )
            model.AddExactlyOne(choices)
            if source.fixed_start is not None:
                model.Add(start == source.fixed_start)
            else:
                model.Add(start >= scenario.current_time)
            if previous_end is None:
                model.Add(start >= scenario.jobs[j].release_time)
            else:
                model.Add(start >= previous_end)
            previous_end = end
        if scenario.jobs[j].deadline is not None:
            model.Add(previous_end <= scenario.jobs[j].deadline)
        limit = scenario.completion_limits.get(scenario.jobs[j].job_id)
        if limit is not None:
            model.Add(previous_end <= limit)
        last_ends.append(previous_end)
    for m, machine in enumerate(scenario.machines):
        for a, (start, end) in enumerate(machine.unavailable_intervals):
            intervals[m].append(
                model.NewIntervalVar(start, end - start, end, f"downtime_{m}_{a}")
            )
        model.AddNoOverlap(intervals[m])
    makespan = model.NewIntVar(0, horizon, "makespan")
    model.AddMaxEquality(makespan, last_ends)
    model.Minimize(makespan)
    return model, {"starts": starts, "presences": presences}
