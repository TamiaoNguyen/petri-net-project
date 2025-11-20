from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
import xml.etree.ElementTree as ET


class Error(Exception):
    pass

# ---------- DATA STRUCTURES ----------
@dataclass
class Place:
    id: str
    name: Optional[str] = None
    initial_marking: int = 0
    incoming: List[str] = field(default_factory=list)  # arc ids
    outgoing: List[str] = field(default_factory=list)
@dataclass
class Transition:
    id: str
    name: Optional[str] = None
    incoming: List[str] = field(default_factory=list)  # arc ids
    outgoing: List[str] = field(default_factory=list)
@dataclass
class Arc:
    id: str
    source: str
    target: str
    weight: int = 1
@dataclass
class PetriNet:
    id: Optional[str]
    places: Dict[str, Place]
    transitions: Dict[str, Transition]
    arcs: Dict[str, Arc]

    def summary(self) -> str:
        return (
            f"PetriNet Summary : places={len(self.places)}, "
            f"transitions={len(self.transitions)}, arcs={len(self.arcs)}"
        )
def strip_namespace(elem: ET.Element):
    if elem.tag is None:
        return
    if '}' in elem.tag:
        elem.tag = elem.tag.split('}', 1)[1]
    for child in list(elem):
        strip_namespace(child)

# ---------- Read .PNML file construct (removing brackets etc.) ----------

def parseText(parent: ET.Element, *path_parts: str) -> Optional[str]:
    elem = parent
    for part in path_parts:
        elem = elem.find(part)
        if elem is None:
            return None
    # has text children -> <text>
    if elem is not None and elem.text and elem.text.strip():
        return elem.text.strip()
    # <name><text>child
    child = elem.find('text') if elem is not None else None
    if child is not None and child.text:
        return child.text.strip()
    return None


def parseInteger(s: Optional[str], default: int = 1) -> int:
    if s is None:
        return default
    try:
        return int(s.strip())
    except ValueError:
        return default


# ---------- Main PNML parsing function ----------

def parsePNML(path: str, require_1safe: bool = True) -> PetriNet:
    tree = ET.parse(path)
    root = tree.getroot()
    #remove namespaces for simpler access
    strip_namespace(root)
    # Find net element (there may be multiple nets; pick the first)
    net_elem = None
    for child in root.findall('net'):
        net_elem = child
        break
    if net_elem is None:
        # sometimes pnml wraps nets directly under root or uses 'pnml' root
        net_elem = root.find('net')
    if net_elem is None:
        raise Error("No <net> element found in PNML file.")

    net_id = net_elem.get('id')

    places: Dict[str, Place] = {}
    transitions: Dict[str, Transition] = {}
    arcs: Dict[str, Arc] = {}

    # Collect places
    for p in net_elem.findall('place'):
        pid = p.get('id')
        if pid is None:
            raise Error("Found <place> no ID.")
        if pid in places:
            raise Error(f"Duplicate place id: {pid}")
        name = parseText(p, 'name', 'text') or parseText(p, 'name')
        im_text = parseText(p, 'initialMarking', 'text') or parseText(p, 'initialMarking') or parseText(p, 'initial-marking')
        initial_marking = parseInteger(im_text, default=0)
        places[pid] = Place(id=pid, name=name, initial_marking=initial_marking)

    # Collect transitions
    for t in net_elem.findall('transition'):
        tid = t.get('id')
        if tid is None:
            raise Error("Found <transition> no ID.")
        if tid in transitions:
            raise Error(f"Duplicate transition id: {tid}")
        name = parseText(t, 'name', 'text') or parseText(t, 'name')
        transitions[tid] = Transition(id=tid, name=name)

    # Collect arcs
    for a in net_elem.findall('arc'):
        aid = a.get('id')
        if aid is None:
            raise Error(f"Found <arc> no ID.")
        if aid in arcs:
            raise Error(f"Duplicate arc id: {aid}")
        source = a.get('source')
        target = a.get('target')
        if source is None or target is None:
            raise Error(f"Arc {aid} no SOURCE/TARGET.")
        # <inscription><text> or <inscription><value>
        weight_text = parseText(a, 'inscription', 'text') or parseText(a, 'inscription') or parseText(a, 'inscription', 'value')
        weight = parseInteger(weight_text, default=1)
        if weight <= 0:
            raise Error(f"Arc {aid} <=0, got {weight}")
        arcs[aid] = Arc(id=aid, source=source, target=target, weight=weight)

    # Validate arcs reference existing nodes
    def node_exists(node_id: str) -> bool:
        return node_id in places or node_id in transitions

    for aid, arc in arcs.items():
        if not node_exists(arc.source):
            raise Error(f"Arc {aid} source '{arc.source}' not found.")
        if not node_exists(arc.target):
            raise Error(f"Arc {aid} target '{arc.target}' not found.")
        # attach arc references to nodes
        if arc.source in places:
            places[arc.source].outgoing.append(aid)
        else:
            transitions[arc.source].outgoing.append(aid)
        if arc.target in places:
            places[arc.target].incoming.append(aid)
        else:
            transitions[arc.target].incoming.append(aid)

    # CHECK FOR ISOLATED NODES
    isolated_nodes = []
    for pid, p in places.items():
        if not p.incoming and not p.outgoing:
            isolated_nodes.append(("place", pid))
    for tid, t in transitions.items():
        if not t.incoming and not t.outgoing:
            isolated_nodes.append(("transition", tid))
    if isolated_nodes:
        msgs = ", ".join([f"{kind} '{nid}'" for kind, nid in isolated_nodes])
        raise Error(f"Isolated nodes found (no arcs): {msgs}")

    # CHECK 1-SAFE CONSTRAINTS
    if require_1safe:
        # initial markings must be 0 or 1
        bad_markings = [(pid, p.initial_marking) for pid, p in places.items() if p.initial_marking not in (0, 1)]
        if bad_markings:
            raise Error(
                "Non-binary initial markings detected: " +
                ", ".join([f"{pid}={val}" for pid, val in bad_markings])
            )
        # arc weights must be 1
        heavy_arcs = [aid for aid, a in arcs.items() if a.weight != 1]
        if heavy_arcs:
            raise Error(
                "Arc weights != 1 detected (violates simple 1-safe requirement): " + ", ".join(heavy_arcs)
            )

    return PetriNet(id=net_id, places=places, transitions=transitions, arcs=arcs)
# ---------- printing -----------
def printPetriNetDetails(net: PetriNet):
    """
    Print details of places, transitions, and arcs in the Petri net.
    """
    print("Places:")
    for p in net.places.values():
        print(f" - {p.id} name={p.name!r} init={p.initial_marking} in={len(p.incoming)} out={len(p.outgoing)}")
    print("Transitions:")
    for t in net.transitions.values():
        print(f" - {t.id} name={t.name!r} in={len(t.incoming)} out={len(t.outgoing)}")
    print("Arcs:")
    for a in net.arcs.values():
        print(f" - {a.id}: {a.source} -> {a.target} weight={a.weight}")
# ---------- BFS - DFS ----------
def compute_reachable_markings(petrinet: PetriNet, dfs: bool = 0):
    """
    Compute reachable markings using BFS (default) or DFS (dfs=True).
    """
    # Precompute input/output place sets for each transition
    pre = {}
    post = {}

    for tid, t in petrinet.transitions.items():
        pre[tid] = set()
        post[tid] = set()
        for aid in t.incoming:
            arc = petrinet.arcs[aid]
            if arc.source in petrinet.places:
                pre[tid].add(arc.source)
        for aid in t.outgoing:
            arc = petrinet.arcs[aid]
            if arc.target in petrinet.places:
                post[tid].add(arc.target)

    # Initial marking
    M0 = frozenset(p for p, pl in petrinet.places.items() if pl.initial_marking > 0)

    visited = set()
    container = [M0]  # acts as queue (BFS) or stack (DFS)
    reachable_markings = []

    while container:
        # choose pop method depending on BFS/DFS
        if dfs:
            M = container.pop()        # DFS: pop from end
        else:
            M = container.pop(0)       # BFS: pop from front

        if M not in visited:
            visited.add(M)
            reachable_markings.append(M)
            for tid in sorted(petrinet.transitions.keys()):  # deterministic order
                if all(p in M for p in pre[tid]):
                    new_marking = frozenset((M - pre[tid]) | post[tid])
                    if new_marking not in visited:
                        container.append(new_marking)

    return reachable_markings

def printBFS(net: PetriNet):
    markings = compute_reachable_markings(net, dfs=0)
    print(f"Reachable markings BFS ({len(markings)}):")
    for m in markings:
        print(sorted(m))

def printDFS(net: PetriNet):
    markings = compute_reachable_markings(net, dfs=1)
    print(f"Reachable markings DFS ({len(markings)}):")
    for m in markings:
        print(sorted(m))
# ---------- PARSE ERROR ----------------------
def handleParseErrors(func):
    """
    Decorator to handle PNMLParseError and ET.ParseError exceptions.
    """
    import sys
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Error as e:
            print("PNML parse/validation error:", e, file=sys.stderr)
            sys.exit(2)
        except ET.ParseError as e:
            print("XML parse error:", e, file=sys.stderr)
            sys.exit(3)
    return wrapper
# ---------- Simple CLI-style usage & an example PNML (for testing) ----------
@handleParseErrors
def main():
    import argparse
    import sys
    parser = argparse.ArgumentParser()
    parser.add_argument("pnml_file")
    args = parser.parse_args()

    net = parsePNML(args.pnml_file, require_1safe=True)
    # SHOW NUMBERS OF PLACES, TRANSITIONS, ARCS
    print(net.summary())
    # DETAILED PRINT OF NODES TRANSITIONS ARCS
    printPetriNetDetails(net)
    # COMPUTE REACHABLE MARKINGS VIA BFS AND DFS
    printBFS(net)
    printDFS(net)

if __name__ == "__main__":
    main()
    #to run in terminal: python pnml_parser.py  pnml_file.pnml
            