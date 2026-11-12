# Lab environment

This directory contains the pinned kind cluster config, chart values, observer RBAC, and the vendored Online Boutique v0.10.7 release manifest. The lab installer applies that manifest into `online-boutique`, exposes only the frontend through a mapped NodePort, and installs Prometheus, kube-state-metrics, Loki, Alloy log collection, Grafana, and Argo CD. The incident app receives a separate short-lived read-only Kubernetes token. Run lab scripts only against the `kind-incident-to-pr` context.

The Online Boutique manifest is from the [GoogleCloudPlatform/microservices-demo v0.10.7 release](https://github.com/GoogleCloudPlatform/microservices-demo/tree/v0.10.7) and is distributed under its accompanying upstream license. The kind node image is pinned by digest. Prometheus 29.47.2, kube-state-metrics 9.0.1, Loki 7.6.0, Alloy 1.15.0, Grafana 10.5.15, and Argo CD v3.6.1 are pinned in `scripts/lab-up.ps1`.
