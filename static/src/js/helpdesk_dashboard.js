/** @odoo-module **/
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, useState, onWillStart } from "@odoo/owl";

const STATUS_COLORS = {
    new: "#2563EB",
    open: "#3B82F6",
    in_progress: "#F59E0B",
    pending_customer: "#8B5CF6",
    pending_internal: "#6366F1",
    resolved: "#16A34A",
    closed: "#1E293B",
    cancelled: "#94A3B8",
};

const PRIORITY_COLORS = {
    "3": "#DC2626",
    "2": "#F59E0B",
    "1": "#2563EB",
    "0": "#64748B",
};

export class HelpdeskProDashboard extends Component {
    static template = "helpdeskpro.Dashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.state = useState({
            dateRange: "30d",
            teamId: "",
            data: null,
            loading: true,
        });

        onWillStart(async () => {
            await this.fetchDashboardData();
        });
    }

    async fetchDashboardData() {
        this.state.loading = true;
        try {
            const teamId = this.state.teamId ? parseInt(this.state.teamId, 10) : false;
            const data = await this.orm.call(
                "helpdesk.ticket",
                "get_dashboard_data",
                [this.state.dateRange, teamId]
            );
            this.state.data = data;
        } catch (err) {
            console.error("Failed to load HelpDeskPro dashboard data:", err);
        } finally {
            this.state.loading = false;
        }
    }

    async onDateRangeChange(ev) {
        this.state.dateRange = ev.target.value;
        await this.fetchDashboardData();
    }

    async onTeamChange(ev) {
        this.state.teamId = ev.target.value;
        await this.fetchDashboardData();
    }

    get kpiCards() {
        if (!this.state.data) return [];
        const k = this.state.data.kpis;
        return [
            {
                key: "total",
                label: "Total Tickets",
                value: k.total,
                sub: `${k.pending} pending wait`,
                icon: "fa-ticket",
                color: "#1E293B",
                bg: "#F1F5F9",
            },
            {
                key: "new",
                label: "New Tickets",
                value: k.new,
                sub: "Awaiting triage",
                icon: "fa-bolt",
                color: "#2563EB",
                bg: "#EFF6FF",
            },
            {
                key: "open",
                label: "Open Tickets",
                value: k.open,
                sub: "Acknowledged",
                icon: "fa-folder-open-o",
                color: "#3B82F6",
                bg: "#EFF6FF",
            },
            {
                key: "in_progress",
                label: "In Progress",
                value: k.in_progress,
                sub: "Active investigation",
                icon: "fa-cogs",
                color: "#F59E0B",
                bg: "#FEF3C7",
            },
            {
                key: "resolved",
                label: "Resolved Tickets",
                value: k.resolved,
                sub: "Solution provided",
                icon: "fa-check-circle",
                color: "#16A34A",
                bg: "#DCFCE7",
            },
            {
                key: "closed",
                label: "Closed Tickets",
                value: k.closed,
                sub: "Completed & archived",
                icon: "fa-archive",
                color: "#1E293B",
                bg: "#F1F5F9",
            },
            {
                key: "overdue",
                label: "Overdue Tickets",
                value: k.overdue,
                sub: "Past SLA or deadline",
                icon: "fa-exclamation-triangle",
                color: "#DC2626",
                bg: "#FEE2E2",
            },
            {
                key: "unassigned",
                label: "Unassigned Tickets",
                value: k.unassigned,
                sub: "Needs agent owner",
                icon: "fa-user-times",
                color: "#D97706",
                bg: "#FEF3C7",
            },
            {
                key: "avg_res",
                label: "Avg Resolution Time",
                value: `${k.avg_resolution_hours}h`,
                sub: "Mean time to resolve",
                icon: "fa-clock-o",
                color: "#2563EB",
                bg: "#EFF6FF",
            },
            {
                key: "sla_rate",
                label: "SLA Compliance Rate",
                value: `${k.sla_compliance_rate}%`,
                sub: k.csat_avg ? `CSAT ${k.csat_avg} / 5.0` : "Target >= 95%",
                icon: "fa-shield",
                color: k.sla_compliance_rate >= 90 ? "#16A34A" : "#DC2626",
                bg: k.sla_compliance_rate >= 90 ? "#DCFCE7" : "#FEE2E2",
            },
        ];
    }

    get statusBars() {
        if (!this.state.data) return [];
        const list = this.state.data.by_status || [];
        const max = Math.max(...list.map((i) => i.count), 1);
        return list.map((item) => ({
            ...item,
            pct: Math.round((item.count / max) * 100),
            color: STATUS_COLORS[item.key] || "#2563EB",
        }));
    }

    get priorityBars() {
        if (!this.state.data) return [];
        const list = this.state.data.by_priority || [];
        const max = Math.max(...list.map((i) => i.count), 1);
        return list.map((item) => ({
            ...item,
            pct: Math.round((item.count / max) * 100),
            color: PRIORITY_COLORS[item.key] || "#2563EB",
        }));
    }

    get teamBars() {
        if (!this.state.data) return [];
        const list = this.state.data.by_team || [];
        const max = Math.max(...list.map((i) => i.count), 1);
        return list.map((item) => ({
            ...item,
            pct: Math.round((item.count / max) * 100),
        }));
    }

    get createdTimeline() {
        if (!this.state.data) return [];
        const list = this.state.data.created_series || [];
        const max = Math.max(...list.map((i) => i.count), 1);
        return list.map((item) => ({
            ...item,
            pct: item.count ? Math.max(Math.round((item.count / max) * 100), 10) : 2,
        }));
    }

    get resolvedTimeline() {
        if (!this.state.data) return [];
        const list = this.state.data.resolved_series || [];
        const max = Math.max(...list.map((i) => i.count), 1);
        return list.map((item) => ({
            ...item,
            pct: item.count ? Math.max(Math.round((item.count / max) * 100), 10) : 2,
        }));
    }

    buildBaseDomain() {
        const domain = [];
        if (this.state.teamId) {
            domain.push(["team_id", "=", parseInt(this.state.teamId, 10)]);
        }
        if (this.state.data && this.state.data.date_from) {
            domain.push(["create_date", ">=", this.state.data.date_from]);
        }
        return domain;
    }

    openKpiCard(key) {
        const domain = this.buildBaseDomain();
        let title = "Support Tickets";
        if (key === "new") {
            domain.push(["state", "=", "new"]);
            title = "New Tickets";
        } else if (key === "open") {
            domain.push(["state", "=", "open"]);
            title = "Open Tickets";
        } else if (key === "in_progress") {
            domain.push(["state", "=", "in_progress"]);
            title = "In Progress Tickets";
        } else if (key === "resolved") {
            domain.push(["state", "=", "resolved"]);
            title = "Resolved Tickets";
        } else if (key === "closed") {
            domain.push(["state", "=", "closed"]);
            title = "Closed Tickets";
        } else if (key === "overdue") {
            domain.push(["is_overdue", "=", true]);
            title = "Overdue Tickets";
        } else if (key === "unassigned") {
            domain.push(["user_id", "=", false]);
            domain.push(["state", "in", ["new", "open", "in_progress", "pending_customer", "pending_internal"]]);
            title = "Unassigned Active Tickets";
        } else if (key === "avg_res") {
            domain.push(["state", "in", ["resolved", "closed"]]);
            title = "Resolved & Closed Tickets";
        } else if (key === "sla_rate") {
            domain.push(["sla_id", "!=", false]);
            title = "SLA Tracked Tickets";
        }

        this.actionService.doAction({
            type: "ir.actions.act_window",
            name: title,
            res_model: "helpdesk.ticket",
            domain,
            views: [[false, "list"], [false, "kanban"], [false, "form"]],
            target: "current",
        });
    }

    openFilteredTickets(field, value, label) {
        const domain = this.buildBaseDomain();
        domain.push([field, "=", value]);
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name: `Tickets – ${label}`,
            res_model: "helpdesk.ticket",
            domain,
            views: [[false, "list"], [false, "kanban"], [false, "form"]],
            target: "current",
        });
    }

    openTicket(ticketId) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "helpdesk.ticket",
            res_id: ticketId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    createNewTicket() {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name: "New Support Ticket",
            res_model: "helpdesk.ticket",
            views: [[false, "form"]],
            target: "current",
        });
    }
}

registry.category("actions").add("helpdeskpro_dashboard", HelpdeskProDashboard);
