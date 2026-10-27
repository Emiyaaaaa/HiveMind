package io.agentflow.api.service;

public class ProjectNotFoundException extends RuntimeException {

    public ProjectNotFoundException() {
        super("Project not found");
    }
}
