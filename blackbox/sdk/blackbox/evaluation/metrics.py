"""
Evaluation metrics for diagnosis models.
"""
from typing import List, Dict, Any
import numpy as np


class DiagnosisMetrics:
    """
    Compute evaluation metrics for failure diagnosis.
    """
    
    @staticmethod
    def top_k_accuracy(
        predictions: List[List[str]],
        ground_truth: List[str],
        k: int = 1
    ) -> float:
        """
        Compute top-k accuracy.
        
        Args:
            predictions: List of ranked event ID lists (one per run)
            ground_truth: List of true culprit event IDs
            k: Top-k to consider
            
        Returns:
            Top-k accuracy score
        """
        if len(predictions) != len(ground_truth):
            raise ValueError("Predictions and ground truth must have same length")
        
        correct = 0
        for pred_ranking, true_culprit in zip(predictions, ground_truth):
            if true_culprit in pred_ranking[:k]:
                correct += 1
        
        return correct / len(predictions) if predictions else 0.0
    
    @staticmethod
    def mean_reciprocal_rank(
        predictions: List[List[str]],
        ground_truth: List[str]
    ) -> float:
        """
        Compute Mean Reciprocal Rank (MRR).
        
        Args:
            predictions: List of ranked event ID lists
            ground_truth: List of true culprit event IDs
            
        Returns:
            MRR score
        """
        if len(predictions) != len(ground_truth):
            raise ValueError("Predictions and ground truth must have same length")
        
        reciprocal_ranks = []
        for pred_ranking, true_culprit in zip(predictions, ground_truth):
            try:
                rank = pred_ranking.index(true_culprit) + 1
                reciprocal_ranks.append(1.0 / rank)
            except ValueError:
                # True culprit not in ranking
                reciprocal_ranks.append(0.0)
        
        return np.mean(reciprocal_ranks) if reciprocal_ranks else 0.0
    
    @staticmethod
    def average_rank(
        predictions: List[List[str]],
        ground_truth: List[str]
    ) -> float:
        """
        Compute average rank of true culprit.
        
        Args:
            predictions: List of ranked event ID lists
            ground_truth: List of true culprit event IDs
            
        Returns:
            Average rank
        """
        if len(predictions) != len(ground_truth):
            raise ValueError("Predictions and ground truth must have same length")
        
        ranks = []
        for pred_ranking, true_culprit in zip(predictions, ground_truth):
            try:
                rank = pred_ranking.index(true_culprit) + 1
                ranks.append(rank)
            except ValueError:
                # Assign worst rank
                ranks.append(len(pred_ranking) + 1)
        
        return np.mean(ranks) if ranks else 0.0
    
    @staticmethod
    def counterfactual_success_rate(
        counterfactual_results: List[Dict[str, Any]]
    ) -> float:
        """
        Compute success rate of counterfactual validations.
        
        Args:
            counterfactual_results: List of counterfactual run results
            
        Returns:
            Success rate (proportion where outcome changed to SUCCESS)
        """
        if not counterfactual_results:
            return 0.0
        
        successes = sum(
            1 for result in counterfactual_results
            if result.get('validation', {}).get('supported', False)
        )
        
        return successes / len(counterfactual_results)
    
    @staticmethod
    def confidence_calibration(
        confidences: List[float],
        correctness: List[bool],
        num_bins: int = 10
    ) -> Dict[str, Any]:
        """
        Compute confidence calibration metrics.
        
        Args:
            confidences: List of confidence scores
            correctness: List of boolean indicating if top-1 prediction was correct
            num_bins: Number of calibration bins
            
        Returns:
            Dictionary with calibration metrics
        """
        if len(confidences) != len(correctness):
            raise ValueError("Confidences and correctness must have same length")
        
        # Create bins
        bins = np.linspace(0, 1, num_bins + 1)
        bin_indices = np.digitize(confidences, bins) - 1
        
        # Compute accuracy per bin
        bin_accuracies = []
        bin_confidences = []
        bin_counts = []
        
        for i in range(num_bins):
            mask = bin_indices == i
            if np.sum(mask) > 0:
                bin_acc = np.mean([correctness[j] for j in range(len(correctness)) if mask[j]])
                bin_conf = np.mean([confidences[j] for j in range(len(confidences)) if mask[j]])
                bin_accuracies.append(bin_acc)
                bin_confidences.append(bin_conf)
                bin_counts.append(np.sum(mask))
            else:
                bin_accuracies.append(0.0)
                bin_confidences.append(0.0)
                bin_counts.append(0)
        
        # Expected Calibration Error (ECE)
        ece = 0.0
        total_count = len(confidences)
        for acc, conf, count in zip(bin_accuracies, bin_confidences, bin_counts):
            ece += (count / total_count) * abs(acc - conf)
        
        return {
            'ece': ece,
            'bin_accuracies': bin_accuracies,
            'bin_confidences': bin_confidences,
            'bin_counts': bin_counts,
        }
    
    @staticmethod
    def compute_all_metrics(
        predictions: List[List[str]],
        ground_truth: List[str],
        confidences: List[float] = None
    ) -> Dict[str, float]:
        """
        Compute all standard metrics.
        
        Args:
            predictions: List of ranked event ID lists
            ground_truth: List of true culprit event IDs
            confidences: Optional list of confidence scores
            
        Returns:
            Dictionary of metrics
        """
        metrics = {
            'top_1_accuracy': DiagnosisMetrics.top_k_accuracy(predictions, ground_truth, k=1),
            'top_3_accuracy': DiagnosisMetrics.top_k_accuracy(predictions, ground_truth, k=3),
            'top_5_accuracy': DiagnosisMetrics.top_k_accuracy(predictions, ground_truth, k=5),
            'mrr': DiagnosisMetrics.mean_reciprocal_rank(predictions, ground_truth),
            'average_rank': DiagnosisMetrics.average_rank(predictions, ground_truth),
        }
        
        if confidences:
            correctness = [
                ground_truth[i] == predictions[i][0] if predictions[i] else False
                for i in range(len(predictions))
            ]
            calibration = DiagnosisMetrics.confidence_calibration(confidences, correctness)
            metrics['ece'] = calibration['ece']
        
        return metrics
