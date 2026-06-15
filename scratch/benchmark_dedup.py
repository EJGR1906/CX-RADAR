import timeit
import random

class Dummy:
    pass

objs = [Dummy() for _ in range(5)]
lst1 = [objs[0], objs[1], objs[2]]
lst2 = [objs[2], objs[3], objs[4]]

def current_approach(nq_targets, upload_nq_targets):
    _seen_ids = set()
    all_nq_targets_list = []
    for t in nq_targets + upload_nq_targets:
        tid = id(t)
        if tid not in _seen_ids:
            _seen_ids.add(tid)
            all_nq_targets_list.append(t)
    return all_nq_targets_list

def opt1(nq_targets, upload_nq_targets):
    return list({id(t): t for t in nq_targets + upload_nq_targets}.values())

print([id(t) for t in current_approach(lst1, lst2)])
print([id(t) for t in opt1(lst1, lst2)])
assert current_approach(lst1, lst2) == opt1(lst1, lst2)

t1 = timeit.timeit(lambda: current_approach(lst1, lst2), number=100000)
t2 = timeit.timeit(lambda: opt1(lst1, lst2), number=100000)

print(f"Current: {t1:.4f}s")
print(f"Opt1 dict comp: {t2:.4f}s")
