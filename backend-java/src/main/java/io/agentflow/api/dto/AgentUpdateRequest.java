package io.agentflow.api.dto;

import java.util.Map;

public class AgentUpdateRequest {

    private String name;
    private String description;
    private String adapter;
    private Map<String, Object> config;
    private String note;

    private boolean nameSet;
    private boolean descriptionSet;
    private boolean adapterSet;
    private boolean configSet;

    public String getName() {
        return name;
    }

    public void setName(String name) {
        this.name = name;
        this.nameSet = true;
    }

    public String getDescription() {
        return description;
    }

    public void setDescription(String description) {
        this.description = description;
        this.descriptionSet = true;
    }

    public String getAdapter() {
        return adapter;
    }

    public void setAdapter(String adapter) {
        this.adapter = adapter;
        this.adapterSet = true;
    }

    public Map<String, Object> getConfig() {
        return config;
    }

    public void setConfig(Map<String, Object> config) {
        this.config = config;
        this.configSet = true;
    }

    public String getNote() {
        return note;
    }

    public void setNote(String note) {
        this.note = note;
    }

    public boolean isNameSet() {
        return nameSet;
    }

    public boolean isDescriptionSet() {
        return descriptionSet;
    }

    public boolean isAdapterSet() {
        return adapterSet;
    }

    public boolean isConfigSet() {
        return configSet;
    }
}
