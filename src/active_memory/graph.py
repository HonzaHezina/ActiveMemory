import json
import os
from pathlib import Path

from neo4j import GraphDatabase


class ReferenceGraph:
    """Persistent offline adapter for development; no embeddings or semantic inference."""

    def __init__(self, directory: Path, scope):
        self.path = directory / "reference-graph.json"
        self.scope = scope

    def load(self):
        if not self.path.exists():
            return {"scope": self.scope, "nodes": {}, "edges": {}}
        state = json.loads(self.path.read_text())
        if state["scope"] != self.scope:
            raise ValueError("graph belongs to another scope")
        return state

    def save(self, state):
        temp = self.path.with_suffix(".tmp")
        with temp.open("w") as stream:
            json.dump(state, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        temp.replace(self.path)

    def close(self):
        pass


class Neo4jGraph:
    """Native nodes/relations; snapshot persistence suits one personal memory, one writer."""

    def __init__(self, settings):
        self.scope = settings.scope
        self.database = settings.neo4j_database
        self.driver = GraphDatabase.driver(
            settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password)
        )
        self.driver.verify_connectivity()
        with self.driver.session(database=self.database) as session:
            session.run(
                "CREATE CONSTRAINT am_node_id IF NOT EXISTS FOR (n:AMNode) REQUIRE n.id IS UNIQUE"
            ).consume()

    def load(self):
        with self.driver.session(database=self.database) as session:
            nodes = {
                r["id"]: json.loads(r["payload"])
                for r in session.run(
                    "MATCH (n:AMNode {scope:$scope}) RETURN n.id AS id,n.payload AS payload",
                    scope=self.scope,
                )
            }
            edges = {
                r["id"]: json.loads(r["payload"])
                for r in session.run(
                    "MATCH (:AMNode {scope:$scope})-[r]->(:AMNode {scope:$scope}) "
                    "WHERE r.am=true RETURN r.id AS id,r.payload AS payload",
                    scope=self.scope,
                )
            }
        return {"scope": self.scope, "nodes": nodes, "edges": edges}

    def save(self, state):
        from .models import Kind, Relation

        # Types come only from allowlisted enums, never from interpolated user data.
        def write(tx):
            tx.run(
                "MATCH (n:AMNode {scope:$scope}) WHERE NOT n.id IN $ids DETACH DELETE n",
                scope=self.scope,
                ids=list(state["nodes"]),
            ).consume()
            tx.run(
                "MATCH (:AMNode {scope:$scope})-[r]->(:AMNode {scope:$scope}) "
                "WHERE r.am=true DELETE r",
                scope=self.scope,
            ).consume()
            for kind in Kind:
                rows = [
                    {
                        "id": n["id"],
                        "label": n["label"],
                        "summary": n["summary"],
                        "status": n["status"],
                        "strength": n.get("strength", 1),
                        "payload": json.dumps(n, ensure_ascii=False),
                    }
                    for n in state["nodes"].values()
                    if n["kind"] == kind
                ]
                tx.run(
                    f"UNWIND $rows AS row MERGE (n:AMNode:{kind.value} {{id:row.id}}) "
                    "SET n += row,n.scope=$scope",
                    rows=rows,
                    scope=self.scope,
                ).consume()
            for relation in Relation:
                rows = [
                    {
                        "id": e["id"],
                        "source": e["source_id"],
                        "target": e["target_id"],
                        "status": e["status"],
                        "payload": json.dumps(e, ensure_ascii=False),
                    }
                    for e in state["edges"].values()
                    if e["relation"] == relation
                ]
                tx.run(
                    "UNWIND $rows AS row MATCH (s:AMNode {id:row.source,scope:$scope}),"
                    "(t:AMNode {id:row.target,scope:$scope}) "
                    f"MERGE (s)-[r:{relation.value} {{id:row.id}}]->(t) "
                    "SET r.am=true,r.status=row.status,r.payload=row.payload",
                    rows=rows,
                    scope=self.scope,
                ).consume()

        with self.driver.session(database=self.database) as session:
            session.execute_write(write)

    def close(self):
        self.driver.close()
