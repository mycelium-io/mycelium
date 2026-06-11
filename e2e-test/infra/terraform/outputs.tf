output "orchestrator_ip" {
  description = "Public IP of the orchestrator node (runs Matrix, backend, tests)"
  value       = aws_instance.node["orchestrator"].public_ip
}

output "node2_ip" {
  description = "Public IP of agent node 2"
  value       = aws_instance.node["node2"].public_ip
}

output "node3_ip" {
  description = "Public IP of agent node 3"
  value       = aws_instance.node["node3"].public_ip
}

output "orchestrator_private_ip" {
  description = "Private IP of orchestrator (used for inter-node config)"
  value       = aws_instance.node["orchestrator"].private_ip
}

output "node2_private_ip" {
  description = "Private IP of node 2"
  value       = aws_instance.node["node2"].private_ip
}

output "node3_private_ip" {
  description = "Private IP of node 3"
  value       = aws_instance.node["node3"].private_ip
}

output "all_private_ips" {
  description = "Map of node name to private IP"
  value = {
    for k, v in aws_instance.node : k => v.private_ip
  }
}
