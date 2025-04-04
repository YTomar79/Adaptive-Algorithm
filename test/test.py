import plotly.graph_objects as go
import numpy as np
from sklearn.decomposition import PCA
from qiskit import transpile
from qiskit_ibm_runtime import QiskitRuntimeService
import matplotlib.pyplot as plt
from scipy import stats  # for statistical tests
import copy


# initialize quantum services with latest authentication pattern 
service = QiskitRuntimeService() 
backend = service.least_busy(simulator=False, operational=True)  

class QuantumStateVisualizer:
    def __init__(self, checkpoint_path, num_qubits=10, num_steps=200):
        self.checkpoint_path = checkpoint_path
        self.env = QuantumCircuitEnvExpanded(num_qubits=num_qubits, backend=backend)
        state_size = self.env._get_observation().shape[0]
        self.agent = PPOAgent(state_size, action_size=16)
        self.episode = self.agent.load_checkpoint(self.checkpoint_path)

        self.pca = PCA(n_components=3)
        self.num_steps = num_steps
        self.state_history = []
        self.fidelity_history = []
        self.depth_history = []
        self.initial_circuit = None  
        self.final_circuit = None


    def _collect_state_data(self):
        self.state_history = []
        self.fidelity_history = []
        self.depth_history = []

        state = self.env.reset()
        lstm_state = self.agent.lstm_hidden_state
        self.initial_circuit = copy.deepcopy(self.env.current_circuit)

        for step in range(self.num_steps):
            action_mask = self.agent.compute_action_mask(self.env)
            action, _, _, _, lstm_state = self.agent.select_action(state, lstm_state, action_mask)
            next_state, _, done, _ = self.env.step(action)
            true_fidelity = self.env._calculate_fidelity()

            self.state_history.append(next_state.numpy())
            self.fidelity_history.append(true_fidelity)
            self.depth_history.append(self.env.current_circuit.depth())

            if done:
                break
            state = next_state
        self.final_circuit = copy.deepcopy(self.env.current_circuit)

    def _reduce_dimensions(self):
        states = np.array(self.state_history)
        return self.pca.fit_transform(states)

  
    def _clean_circuit(self, circuit):
        """Remove measurement and state-saving operations for visualization"""
        cleaned = copy.deepcopy(circuit)
        cleaned.data = [
            instr for instr in cleaned.data
            if not isinstance(instr.operation, (SaveStatevector))
        ]
        return cleaned
    def optimize_with_qiskit(self, optimization_level=3):
        """
        Use Qiskit's built-in transpiler to optimize the current circuit.
        To avoid transpilation errors, a copy of the current circuit is made and any
        save_statevector instructions are removed from the copy before transpiling.
        Returns the transpiled circuit.
        """
        # get the current circuit from the environment
        original_circuit = self.env.current_circuit

        # create a deep copy of the circuit to leave the original unchanged
        circuit_copy = copy.deepcopy(original_circuit)

        # remove save_statevector instructions from the copy if present.
        circuit_copy.data = [instr for instr in circuit_copy.data if not isinstance(instr.operation, SaveStatevector)]

        # transpile the cleaned circuit copy
        optimized_circuit = transpile(circuit_copy, backend=backend, optimization_level=optimization_level, initial_layout=list(range(10)))
        return optimized_circuit
    def draw_circuit_comparison(self, output_format='mpl'):
        """Draw circuits before and after PPO optimization"""
        if not self.initial_circuit or not self.final_circuit:
            self._collect_state_data()

        #clean 
        before = self._clean_circuit(self.initial_circuit)
        after = self._clean_circuit(self.final_circuit)

        # draw circuits
        print("Before PPO Optimization:")
        display(circuit_drawer(before, output=output_format, 
                             cregbundle=False, 
                             plot_barriers=False,
                             style={'backgroundcolor': '#FFFFFF'}))
        
        print("\nAfter PPO Optimization:")
        display(circuit_drawer(after, output=output_format,
                             cregbundle=False,
                             plot_barriers=False,
                             style={'backgroundcolor': '#F7F7F7'}))


    def compare_optimizers(self, optimization_level=3):
        """
        Compare the PPO optimization to Qiskit's built-in transpiler optimization.
        It prints and plots the circuit depths and (optionally) fidelity estimates.
        """

        original_circuit = self.env.current_circuit

        # run! daddawd
        self._collect_state_data()  
        ppo_depth = self.depth_history[-1]  
        ppo_fidelity = self.fidelity_history[-1]  


        qiskit_optimized_circuit = self.optimize_with_qiskit(optimization_level)
        qiskit_depth = qiskit_optimized_circuit.depth()

        qiskit_fidelity = self.env._calculate_fidelity(qiskit_optimized_circuit)

        print("PPO Optimizer Results:")
        print("  Depth:    {:.2f}".format(ppo_depth))
        print("  Fidelity: {:.3f}".format(ppo_fidelity))
        print("\nQiskit Transpiler Optimization (level {}):".format(optimization_level))
        print("  Depth:    {:.2f}".format(qiskit_depth))
        print("  Fidelity: {:.3f}".format(qiskit_fidelity))

        # plot a simple comparison bar graph:
        plt.figure(figsize=(10, 4))

        plt.subplot(1, 2, 1)
        plt.bar(["PPO", "Qiskit"], [ppo_depth, qiskit_depth], color=["orange", "blue"])
        plt.ylabel("Circuit Depth")
        plt.title("Depth Comparison")
        plt.grid(axis="y")

        plt.subplot(1, 2, 2)
        plt.bar(["PPO", "Qiskit"], [ppo_fidelity, qiskit_fidelity], color=["orange", "blue"])
        plt.ylabel("Fidelity")
        plt.title("Fidelity Comparison")
        plt.grid(axis="y")

        plt.tight_layout()
        plt.show()
    def create_state_space_plot(self):
        if not self.state_history:
            self._collect_state_data()
        transformed = self._reduce_dimensions()

        fig = go.Figure()

        scatter = go.Scatter3d(
            x=transformed[:, 0],
            y=transformed[:, 1],
            z=transformed[:, 2],
            mode='markers',
            marker=dict(
                size=8,
                color=self.fidelity_history,
                colorscale='Plasma',
                opacity=0.9,
                line=dict(width=0.5, color='darkslategray'),
                colorbar=dict(title='Fidelity', tickfont=dict(size=12))
            ),
            customdata=np.stack([self.depth_history, self.fidelity_history], axis=-1),
            hovertemplate="<b>Step</b>: %{text}<br>"
                          "<b>Depth</b>: %{customdata[0]}<br>"
                          "<b>Fidelity</b>: %{customdata[1]:.2f}<extra></extra>",
            text=np.arange(len(transformed))
        )
        fig.add_trace(scatter)

        for i in range(len(transformed) - 1):
            fig.add_trace(go.Scatter3d(
                x=[transformed[i, 0], transformed[i + 1, 0]],
                y=[transformed[i, 1], transformed[i + 1, 1]],
                z=[transformed[i, 2], transformed[i + 1, 2]],
                mode='lines',
                line=dict(color='lightgrey', width=2),
                showlegend=False
            ))

        fig.update_layout(
            title=dict(text="Enhanced Quantum State Space Evolution", font=dict(size=24, family="Arial"), x=0.5, xanchor='center'),
            scene=dict(
                xaxis=dict(title="PCA1: Qubit Utilization", showgrid=False, zeroline=False, showbackground=False, tickfont=dict(size=10)),
                yaxis=dict(title="PCA2: Connectivity Pattern", showgrid=False, zeroline=False, showbackground=False, tickfont=dict(size=10)),
                zaxis=dict(title="PCA3: Noise Profile", showgrid=False, zeroline=False, showbackground=False, tickfont=dict(size=10)),
                camera=dict(eye=dict(x=1.8, y=1.8, z=1.8))
            ),
            paper_bgcolor='white',
            plot_bgcolor='white',
            width=1200,
            height=800,
            margin=dict(l=10, r=10, b=10, t=50),
            hovermode='closest',
            updatemenus=[
                dict(
                    type="buttons",
                    buttons=[
                        dict(label="Color by Fidelity", method="restyle",
                             args=[{"marker.color": [self.fidelity_history]}]),
                        dict(label="Color by Depth", method="restyle",
                             args=[{"marker.color": [self.depth_history]}]),
                        dict(label="Color by Time Progression", method="restyle",
                             args=[{"marker.color": [np.arange(len(transformed))]}])
                    ],
                    direction='down',
                    showactive=True,
                    x=0.1,
                    xanchor='left',
                    y=1.15,
                    yanchor='top'
                )
            ]
        )
        return fig

    def create_comparison_plots(self):
        if not self.fidelity_history or not self.depth_history:
            self._collect_state_data()

        fidelity_before = self.fidelity_history[0]
        fidelity_after = self.fidelity_history[-1]
        depth_before = self.depth_history[0]
        depth_after = self.depth_history[-1]

        plt.figure(figsize=(8, 6))
        plt.bar(['Fidelity Before', 'Fidelity After'], [fidelity_before, fidelity_after],
                color=['blue', 'green'])
        plt.title('Fidelity Comparison: Before vs After Optimization')
        plt.ylabel('Fidelity')
        plt.ylim(0, 1)
        plt.grid(axis='y')
        plt.show()

        plt.figure(figsize=(8, 6))
        plt.bar(['Depth Before', 'Depth After'], [depth_before, depth_after],
                color=['red', 'orange'])
        plt.title('Circuit Depth Comparison: Before vs After Optimization')
        plt.ylabel('Depth')
        plt.grid(axis='y')
        plt.show()

    def statistical_validation(self, num_trials=30, confidence=0.95):
        """
        Run the optimizer multiple times and perform a statistical analysis of the results.
        For each trial, record the initial ("before") and final ("after") fidelity and depth.
        Then, compute statistics (mean, standard deviation, confidence intervals) and perform hypothesis testing.
        """
        fidelities_before = []
        fidelities_after = []
        depths_before = []
        depths_after = []

        for _ in range(num_trials):
            self._collect_state_data()
            fidelities_before.append(self.fidelity_history[0])
            fidelities_after.append(self.fidelity_history[-1])
            depths_before.append(self.depth_history[0])
            depths_after.append(self.depth_history[-1])

        # convert to numpy arrays
        fidelities_before = np.array(fidelities_before)
        fidelities_after = np.array(fidelities_after)
        depths_before = np.array(depths_before)
        depths_after = np.array(depths_after)

        # calculate means and standard deviations
        mean_fid_before = np.mean(fidelities_before)
        mean_fid_after = np.mean(fidelities_after)
        std_fid_before = np.std(fidelities_before, ddof=1)
        std_fid_after = np.std(fidelities_after, ddof=1)

        mean_depth_before = np.mean(depths_before)
        mean_depth_after = np.mean(depths_after)
        std_depth_before = np.std(depths_before, ddof=1)
        std_depth_after = np.std(depths_after, ddof=1)

        # compute confidence intervals using t-distribution
        t_val = stats.t.ppf(1 - (1 - confidence) / 2, num_trials - 1)
        ci_fid_before = t_val * std_fid_before / np.sqrt(num_trials)
        ci_fid_after = t_val * std_fid_after / np.sqrt(num_trials)
        ci_depth_before = t_val * std_depth_before / np.sqrt(num_trials)
        ci_depth_after = t_val * std_depth_after / np.sqrt(num_trials)

        # print statistical summary
        print("Fidelity (Before): Mean = {:.3f}, CI = ±{:.3f}".format(mean_fid_before, ci_fid_before))
        print("Fidelity (After):  Mean = {:.3f}, CI = ±{:.3f}".format(mean_fid_after, ci_fid_after))
        print("Depth (Before):    Mean = {:.2f}, CI = ±{:.2f}".format(mean_depth_before, ci_depth_before))
        print("Depth (After):     Mean = {:.2f}, CI = ±{:.2f}".format(mean_depth_after, ci_depth_after))

        # perform paired t-tests
        fid_tstat, fid_pvalue = stats.ttest_rel(fidelities_before, fidelities_after)
        depth_tstat, depth_pvalue = stats.ttest_rel(depths_before, depths_after)
        print("\nPaired t-test for Fidelity: t = {:.3f}, p = {:.3f}".format(fid_tstat, fid_pvalue))
        print("Paired t-test for Depth:    t = {:.3f}, p = {:.3f}".format(depth_tstat, depth_pvalue))

        # create figure with two subplots
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

        # fidelity plot
        bp1 = ax1.boxplot([fidelities_before, fidelities_after], labels=["Before", "After"])
        ax1.errorbar([1, 2], [mean_fid_before, mean_fid_after],
                    yerr=[ci_fid_before, ci_fid_after],
                    fmt='ro', capsize=5, label='95% CI')
        ax1.set_ylabel("Fidelity")
        ax1.set_title("Fidelity Distribution Over {} Trials".format(num_trials))
        ax1.legend()

        # depth plot
        bp2 = ax2.boxplot([depths_before, depths_after], labels=["Before", "After"])
        ax2.errorbar([1, 2], [mean_depth_before, mean_depth_after],
                    yerr=[ci_depth_before, ci_depth_after],
                    fmt='ro', capsize=5, label='95% CI')
        ax2.set_ylabel("Depth")
        ax2.set_title("Depth Distribution Over {} Trials".format(num_trials))
        ax2.legend()

        plt.tight_layout()
        plt.show()

    def compare_optimizers_horizontal(self, optimization_level=3, num_trials=30, confidence=0.95):
        """
        Compare the PPO-based optimizer and Qiskit's transpiler optimizer using horizontal bar charts.
        This method runs multiple trials, computes the means, standard deviations, and 95% confidence intervals
        for both circuit depth and fidelity. It also performs paired t-tests and overlays individual trial data points.
        """
        # initialize lists to collect metrics.
        ppo_depths = []
        ppo_fidelities = []
        qiskit_depths = []
        qiskit_fidelities = []

        for _ in range(num_trials):
            # run adaptive-algorithm optimization.
            self._collect_state_data()  
            ppo_depths.append(self.depth_history[-1])
            ppo_fidelities.append(self.fidelity_history[-1])

            # use the same original circuit for Qiskit optimization.
            original_circuit = self.env.current_circuit
            # create a deep copy and remove any save_statevector instructions.
            circuit_copy = copy.deepcopy(original_circuit)
            # remove instructions by checking the operation name.
            circuit_copy.data = [instr for instr in circuit_copy.data if instr.operation.name != "save_statevector"]

            
            
            qiskit_optimized = transpile(circuit_copy, backend=backend,
                                        optimization_level=optimization_level,
                                        initial_layout=list(range(10)))
            qiskit_depths.append(qiskit_optimized.depth())
            # use the modified fidelity calculation which accepts a circuit.
            qiskit_fidelities.append(self.env._calculate_fidelity(qiskit_optimized))

        # convert lists to NumPy arrays.
        ppo_depths = np.array(ppo_depths)
        ppo_fidelities = np.array(ppo_fidelities)
        qiskit_depths = np.array(qiskit_depths)
        qiskit_fidelities = np.array(qiskit_fidelities)

        # compute means and standard deviations.
        mean_ppo_depth = np.mean(ppo_depths)
        std_ppo_depth  = np.std(ppo_depths, ddof=1)
        mean_ppo_fid = np.mean(ppo_fidelities)
        std_ppo_fid  = np.std(ppo_fidelities, ddof=1)

        mean_qiskit_depth = np.mean(qiskit_depths)
        std_qiskit_depth  = np.std(qiskit_depths, ddof=1)
        mean_qiskit_fid = np.mean(qiskit_fidelities)
        std_qiskit_fid  = np.std(qiskit_fidelities, ddof=1)

        # compute 95% confidence intervals using t-distribution.
        t_val = stats.t.ppf(1 - (1 - confidence) / 2, num_trials - 1)

        ci_ppo_depth = t_val * std_ppo_depth / np.sqrt(num_trials)
        ci_ppo_fid   = t_val * std_ppo_fid / np.sqrt(num_trials)
        ci_qiskit_depth = t_val * std_qiskit_depth / np.sqrt(num_trials)
        ci_qiskit_fid   = t_val * std_qiskit_fid / np.sqrt(num_trials)

        # perform paired t-tests.
        t_stat_depth, p_value_depth = stats.ttest_rel(ppo_depths, qiskit_depths)
        t_stat_fid, p_value_fid = stats.ttest_rel(ppo_fidelities, qiskit_fidelities)

        print("Paired t-test for Depth: t = {:.3f}, p = {:.3f}".format(t_stat_depth, p_value_depth))
        print("Paired t-test for Fidelity: t = {:.3f}, p = {:.3f}".format(t_stat_fid, p_value_fid))

        # prepare data for horizontal bar charts.
        optimizers = ['PPO', 'Qiskit']
        depth_means = [mean_ppo_depth, mean_qiskit_depth]
        depth_cis   = [ci_ppo_depth, ci_qiskit_depth]
        fid_means   = [mean_ppo_fid, mean_qiskit_fid]
        fid_cis     = [ci_ppo_fid, ci_qiskit_fid]

        # create figure with two subplots.
        fig, axes = plt.subplots(1, 2, figsize=(14, 6))

        # depth plot (lower is better; invert x-axis so lower depth appears to the right).
        axes[0].barh(optimizers, depth_means, xerr=depth_cis, color=['orange', 'blue'], alpha=0.75, capsize=8)
        axes[0].set_xlabel("Circuit Depth")
        axes[0].set_title("Circuit Depth Comparison")
        axes[0].invert_xaxis()
        axes[0].grid(axis="x", linestyle='--', alpha=0.7)

        # overlay individual trial scatter points (with horizontal jitter).
        jitter = 0.1
        for i, data in enumerate([ppo_depths, qiskit_depths]):
            y_positions = np.full_like(data, i) + np.random.normal(0, jitter, size=len(data))
            axes[0].scatter(data, y_positions, color='black', alpha=0.7, s=50)

        # fidelity plot (higher = better).
        axes[1].barh(optimizers, fid_means, xerr=fid_cis, color=['orange', 'blue'], alpha=0.75, capsize=8)
        axes[1].set_xlabel("Fidelity")
        axes[1].set_title("Fidelity Comparison")
        axes[1].grid(axis="x", linestyle='--', alpha=0.7)

        # overlay individual trial scatter points (with jitter).
        for i, data in enumerate([ppo_fidelities, qiskit_fidelities]):
            y_positions = np.full_like(data, i) + np.random.normal(0, jitter, size=len(data))
            axes[1].scatter(data, y_positions, color='black', alpha=0.7, s=50)

        # annotate both plots with the p-values from the paired t-tests.
        axes[0].text(0.5, -0.2, "Paired t-test p-value (Depth) = {:.3f}".format(p_value_depth),
                    transform=axes[0].transAxes, fontsize=12, ha='center', color='darkred')
        axes[1].text(0.5, -0.2, "Paired t-test p-value (Fidelity) = {:.3f}".format(p_value_fid),
                    transform=axes[1].transAxes, fontsize=12, ha='center', color='darkred')

        plt.tight_layout()
        plt.show()


if __name__ == "__main__":
    visualizer = QuantumStateVisualizer(
        checkpoint_path="ppo_checkpoint_8800.pt",
        num_qubits=10,
        num_steps=300
    )

    visualizer.statistical_validation() # before and after for fidelity and depth.

    visualizer.compare_optimizers_horizontal() # this is the qiskit vs my algorithm comparison!
    
    visualizer.create_state_space_plot().show() # state space plot
    
    visualizer.draw_circuit_comparison() # draw circuits for proof of optimization

    




