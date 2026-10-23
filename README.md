# Auspex Research: Teaching Small Language Models to Diagnose Network Failures

**How we built a synthetic network laboratory, generated verified troubleshooting data, and trained an 8B-parameter model to investigate real network failures.**

At Calexis Labs, we started with a question:

*Can a relatively small language model learn to troubleshoot complex computer networks without relying on cloud inference or real customer data?*

That question became **Auspex Research**, an experimental framework for generating network failures, collecting expert diagnostic traces, training specialized language models, and evaluating their ability to identify root causes.

We've made the research repository public to share the engineering approach, training pipeline, and lessons learned.

## Building a Network Laboratory That Generates Its Own Problems

Training a specialized AI model requires more than a collection of documentation and troubleshooting guides. It needs examples of actual investigation: what to inspect, which hypothesis to test, and how to distinguish symptoms from root causes.

Collecting this information from production networks introduces significant challenges, including confidentiality, limited access, inconsistent documentation, and a lack of verified ground truth.

Our solution was to generate the data ourselves.

Using **Containerlab, Arista cEOS, and Linux hosts**, we built a programmable network laboratory capable of generating different network topologies.

The topology generator varies VLAN configurations, addressing, routing protocols, device relationships, and other network characteristics. Each topology is generated deterministically from a seed, allowing experiments to be reproduced.

We then deliberately introduce faults, including VLAN misconfigurations, interface failures, routing inconsistencies, OSPF adjacency problems, duplicate IP addresses, and gateway configuration errors.

Every injected fault has a known cause and a defined expected resolution.

This gives us something especially valuable for training: **a network that can fail in controlled ways, with a verifiable answer to every diagnostic problem.**

## Learning from Expert Investigations

Once a fault is introduced, a larger teacher model is asked to investigate it.

Our research pipeline uses Claude through a controlled set of diagnostic tools exposed via MCP.

The teacher can inspect interfaces, retrieve routing information, examine VLANs, discover network neighbors, and perform connectivity tests.

It cannot change device configurations.

Rather than giving the teacher the network topology and correct answer, the system presents a natural-language description of the symptom and allows the model to investigate using the available tools.

Each investigation produces a trace containing tool calls, observations, and a final diagnosis.

A deterministic verifier then compares that diagnosis against the injected fault's ground truth.

Incorrect and incomplete investigations are excluded from the training dataset. Successful traces are converted into structured training conversations that preserve the diagnostic tool
