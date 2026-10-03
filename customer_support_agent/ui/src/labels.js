// Turning the agent's internal vocabulary into something a human reads easily.

export const DECISION_LABEL = {
  APPROVE: 'Approved',
  DENY: 'Denied',
  REQUEST_PHOTO: 'Photo requested',
  ESCALATE: 'Escalated to a manager',
}

export const TOOL_LABEL = {
  verify_customer: 'Verified the customer',
  find_order: 'Searched their orders',
  get_order: 'Pulled the order record',
  get_payment_history: 'Checked what was paid',
  check_policy: 'Looked up store policy',
  check_stock: 'Checked stock',
  take_action: 'Took action on the order',
  verify_action: 'Confirmed the action applied',
  send_reply: 'Replied to the customer',
}

const rupees = (n) =>
  `Rs. ${Number(n).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`

/**
 * One line summarising what a step found, so the timeline is readable without
 * expanding every row. Returns null when there is nothing worth surfacing.
 */
export function stepHeadline(tool, result) {
  if (!result || typeof result !== 'object') return null
  if (result.error) return `error: ${result.error}`

  switch (tool) {
    case 'verify_customer':
      return result.found ? result.name : 'not found'

    case 'find_order':
      return `${result.match_count} order${result.match_count === 1 ? '' : 's'} found`

    case 'get_order': {
      if (!result.found) return 'not found'
      const bits = [
        result.item,
        rupees(result.price),
        `${result.days_since_purchase}d old`,
        result.shipped ? 'shipped' : 'not shipped',
      ]
      if (result.final_sale) bits.push('final sale')
      return bits.join(' · ')
    }

    case 'get_payment_history':
      return `${rupees(result.total_paid)} paid`

    case 'check_policy':
      return result.found ? result.policy_name : 'no policy matched'

    case 'check_stock':
      return result.in_stock ? `${result.quantity} in stock` : 'out of stock'

    case 'take_action':
      if (!result.success) return 'failed'
      return result.dry_run ? 'simulated (dry run)' : 'applied to the store'

    case 'verify_action':
      return `order is now ${result.order_status}`

    case 'send_reply':
      return result.sent ? result.decision : 'rejected'

    default:
      return null
  }
}
