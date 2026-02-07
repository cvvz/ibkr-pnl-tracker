from __future__ import annotations

import datetime as dt

from kubernetes import client, config


def restart_deployment(name: str, namespace: str) -> None:
    config.load_incluster_config()
    api = client.AppsV1Api()
    now = dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc).isoformat()
    body = {
        "spec": {
            "template": {
                "metadata": {
                    "annotations": {
                        "kubectl.kubernetes.io/restartedAt": now
                    }
                }
            }
        }
    }
    api.patch_namespaced_deployment(name=name, namespace=namespace, body=body)
