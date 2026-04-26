import { useState, useEffect } from 'react'
import axios from 'axios'

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1'

// Configure axios
const api = axios.create({
  baseURL: API_BASE,
  headers: {
    'Content-Type': 'application/json',
  },
})

function App() {
  const [merchants, setMerchants] = useState([])
  const [selectedMerchant, setSelectedMerchant] = useState(null)
  const [balance, setBalance] = useState(null)
  const [ledger, setLedger] = useState([])
  const [payouts, setPayouts] = useState([])
  const [bankAccounts, setBankAccounts] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  
  // Payout form state
  const [payoutAmount, setPayoutAmount] = useState('')
  const [selectedBankAccount, setSelectedBankAccount] = useState('')
  const [idempotencyKey, setIdempotencyKey] = useState('')
  const [payoutLoading, setPayoutLoading] = useState(false)
  const [payoutMessage, setPayoutMessage] = useState(null)

  useEffect(() => {
    fetchMerchants()
  }, [])

  useEffect(() => {
    if (selectedMerchant) {
      fetchBalance(selectedMerchant)
      fetchLedger(selectedMerchant)
      fetchPayouts(selectedMerchant)
      fetchBankAccounts(selectedMerchant)
    }
  }, [selectedMerchant])

  async function fetchMerchants() {
    try {
      setLoading(true)
      const response = await api.get('/merchants')
      setMerchants(response.data)
      if (response.data.length > 0) {
        setSelectedMerchant(response.data[0].id)
      }
    } catch (err) {
      setError('Failed to fetch merchants: ' + err.message)
    } finally {
      setLoading(false)
    }
  }

  async function fetchBalance(merchantId) {
    try {
      const response = await api.get(`/merchants/${merchantId}/balance`)
      setBalance(response.data)
    } catch (err) {
      console.error('Failed to fetch balance:', err)
    }
  }

  async function fetchLedger(merchantId) {
    try {
      const response = await api.get(`/merchants/${merchantId}/ledger`)
      setLedger(response.data)
    } catch (err) {
      console.error('Failed to fetch ledger:', err)
    }
  }

  async function fetchPayouts(merchantId) {
    try {
      const response = await api.get(`/payouts?merchant_id=${merchantId}`)
      setPayouts(response.data)
    } catch (err) {
      console.error('Failed to fetch payouts:', err)
    }
  }

  async function fetchBankAccounts(merchantId) {
    try {
      const response = await api.get(`/bank-accounts?merchant_id=${merchantId}`)
      setBankAccounts(response.data)
      if (response.data.length > 0 && !selectedBankAccount) {
        setSelectedBankAccount(response.data[0].id)
      }
    } catch (err) {
      console.error('Failed to fetch bank accounts:', err)
    }
  }

  async function handlePayoutSubmit(e) {
    e.preventDefault()
    
    if (!idempotencyKey) {
      setPayoutMessage({ type: 'error', text: 'Please generate an idempotency key first' })
      return
    }
    
    if (!payoutAmount || payoutAmount <= 0) {
      setPayoutMessage({ type: 'error', text: 'Please enter a valid amount' })
      return
    }
    
    if (!selectedBankAccount) {
      setPayoutMessage({ type: 'error', text: 'Please select a bank account' })
      return
    }
    
    try {
      setPayoutLoading(true)
      setPayoutMessage(null)
      
      const response = await api.post('/payouts', {
        merchant_id: selectedMerchant,
        amount_paise: parseInt(payoutAmount),
        bank_account_id: selectedBankAccount,
      }, {
        headers: {
          'Idempotency-Key': idempotencyKey,
        },
      })
      
      setPayoutMessage({ type: 'success', text: `Payout created successfully! ID: ${response.data.id}` })
      setPayoutAmount('')
      setIdempotencyKey('')
      
      // Refresh data
      fetchBalance(selectedMerchant)
      fetchLedger(selectedMerchant)
      fetchPayouts(selectedMerchant)
    } catch (err) {
      const errorMsg = err.response?.data?.error || err.message
      setPayoutMessage({ type: 'error', text: errorMsg })
    } finally {
      setPayoutLoading(false)
    }
  }

  function generateIdempotencyKey() {
    const key = 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
      const r = Math.random() * 16 | 0
      const v = c === 'x' ? r : (r & 0x3 | 0x8)
      return v.toString(16)
    })
    setIdempotencyKey(key)
  }

  function formatPaise(amount) {
    return (amount / 100).toFixed(2)
  }

  function getStatusColor(state) {
    switch (state) {
      case 'pending': return 'bg-yellow-100 text-yellow-800'
      case 'processing': return 'bg-blue-100 text-blue-800'
      case 'completed': return 'bg-green-100 text-green-800'
      case 'failed': return 'bg-red-100 text-red-800'
      default: return 'bg-gray-100 text-gray-800'
    }
  }

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-xl text-gray-600">Loading...</div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white shadow">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
          <h1 className="text-2xl font-bold text-gray-900">Playto Payout Dashboard</h1>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {error && (
          <div className="mb-4 p-4 bg-red-100 border border-red-400 text-red-700 rounded">
            {error}
          </div>
        )}

        {/* Merchant Selector */}
        <div className="mb-6">
          <label className="block text-sm font-medium text-gray-700 mb-2">
            Select Merchant
          </label>
          <select
            value={selectedMerchant || ''}
            onChange={(e) => setSelectedMerchant(e.target.value)}
            className="mt-1 block w-full pl-3 pr-10 py-2 text-base border-gray-300 focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm rounded-md border"
          >
            <option value="">Select a merchant</option>
            {merchants.map((merchant) => (
              <option key={merchant.id} value={merchant.id}>
                {merchant.name} ({merchant.email})
              </option>
            ))}
          </select>
        </div>

        {selectedMerchant && balance && (
          <>
            {/* Balance Cards */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
              <div className="bg-white overflow-hidden shadow rounded-lg">
                <div className="px-4 py-5 sm:p-6">
                  <dt className="text-sm font-medium text-gray-500 truncate">Available Balance</dt>
                  <dd className="mt-1 text-3xl font-semibold text-gray-900">
                    ₹{formatPaise(balance.available_balance)}
                  </dd>
                </div>
              </div>
              
              <div className="bg-white overflow-hidden shadow rounded-lg">
                <div className="px-4 py-5 sm:p-6">
                  <dt className="text-sm font-medium text-gray-500 truncate">Held Balance</dt>
                  <dd className="mt-1 text-3xl font-semibold text-gray-900">
                    ₹{formatPaise(balance.held_balance)}
                  </dd>
                </div>
              </div>
              
              <div className="bg-white overflow-hidden shadow rounded-lg">
                <div className="px-4 py-5 sm:p-6">
                  <dt className="text-sm font-medium text-gray-500 truncate">Total Credits</dt>
                  <dd className="mt-1 text-3xl font-semibold text-green-600">
                    ₹{formatPaise(balance.total_credits)}
                  </dd>
                </div>
              </div>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
              {/* Payout Request Form */}
              <div className="bg-white shadow rounded-lg">
                <div className="px-4 py-5 sm:p-6">
                  <h3 className="text-lg leading-6 font-medium text-gray-900 mb-4">
                    Request Payout
                  </h3>
                  
                  <form onSubmit={handlePayoutSubmit}>
                    <div className="mb-4">
                      <label className="block text-sm font-medium text-gray-700 mb-2">
                        Amount (in paise)
                      </label>
                      <input
                        type="number"
                        value={payoutAmount}
                        onChange={(e) => setPayoutAmount(e.target.value)}
                        placeholder="Enter amount in paise (e.g., 10000 = ₹100)"
                        className="mt-1 block w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500"
                      />
                      <p className="mt-1 text-sm text-gray-500">
                        100 paise = ₹1
                      </p>
                    </div>
                    
                    <div className="mb-4">
                      <label className="block text-sm font-medium text-gray-700 mb-2">
                        Bank Account
                      </label>
                      <select
                        value={selectedBankAccount}
                        onChange={(e) => setSelectedBankAccount(e.target.value)}
                        className="mt-1 block w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500"
                      >
                        <option value="">Select bank account</option>
                        {bankAccounts.map((account) => (
                          <option key={account.id} value={account.id}>
                            {account.bank_name} - {account.account_holder_name} (****{account.account_number?.slice(-4)})
                          </option>
                        ))}
                      </select>
                    </div>
                    
                    <div className="mb-4">
                      <label className="block text-sm font-medium text-gray-700 mb-2">
                        Idempotency Key
                      </label>
                      <div className="flex">
                        <input
                          type="text"
                          value={idempotencyKey}
                          onChange={(e) => setIdempotencyKey(e.target.value)}
                          placeholder="Generate or enter key"
                          className="mt-1 block w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500"
                        />
                        <button
                          type="button"
                          onClick={generateIdempotencyKey}
                          className="ml-2 mt-1 px-4 py-2 border border-gray-300 rounded-md shadow-sm text-sm font-medium text-gray-700 hover:bg-gray-50"
                        >
                          Generate
                        </button>
                      </div>
                    </div>
                    
                    {payoutMessage && (
                      <div className={`mb-4 p-3 rounded ${
                        payoutMessage.type === 'error' ? 'bg-red-100 text-red-700' : 'bg-green-100 text-green-700'
                      }`}>
                        {payoutMessage.text}
                      </div>
                    )}
                    
                    <button
                      type="submit"
                      disabled={payoutLoading}
                      className="w-full flex justify-center py-2 px-4 border border-transparent rounded-md shadow-sm text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500 disabled:opacity-50"
                    >
                      {payoutLoading ? 'Processing...' : 'Request Payout'}
                    </button>
                  </form>
                </div>
              </div>

              {/* Payout History */}
              <div className="bg-white shadow rounded-lg">
                <div className="px-4 py-5 sm:p-6">
                  <h3 className="text-lg leading-6 font-medium text-gray-900 mb-4">
                    Payout History
                  </h3>
                  
                  {payouts.length === 0 ? (
                    <p className="text-gray-500">No payouts yet</p>
                  ) : (
                    <div className="overflow-x-auto">
                      <table className="min-w-full divide-y divide-gray-200">
                        <thead className="bg-gray-50">
                          <tr>
                            <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                              ID
                            </th>
                            <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                              Amount
                            </th>
                            <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                              Status
                            </th>
                            <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                              Date
                            </th>
                          </tr>
                        </thead>
                        <tbody className="bg-white divide-y divide-gray-200">
                          {payouts.map((payout) => (
                            <tr key={payout.id}>
                              <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-500">
                                {payout.id.slice(0, 8)}...
                              </td>
                              <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900">
                                ₹{formatPaise(payout.amount_paise)}
                              </td>
                              <td className="px-3 py-2 whitespace-nowrap">
                                <span className={`px-2 inline-flex text-xs leading-5 font-semibold rounded-full ${getStatusColor(payout.state)}`}>
                                  {payout.state}
                                </span>
                              </td>
                              <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-500">
                                {new Date(payout.created_at).toLocaleDateString()}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              </div>
            </div>

            {/* Ledger Entries */}
            <div className="mt-8 bg-white shadow rounded-lg">
              <div className="px-4 py-5 sm:p-6">
                <h3 className="text-lg leading-6 font-medium text-gray-900 mb-4">
                  Ledger Entries
                </h3>
                
                {ledger.length === 0 ? (
                  <p className="text-gray-500">No ledger entries yet</p>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="min-w-full divide-y divide-gray-200">
                      <thead className="bg-gray-50">
                        <tr>
                          <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            Type
                          </th>
                          <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            Amount
                          </th>
                          <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            Status
                          </th>
                          <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            Reference
                          </th>
                          <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            Date
                          </th>
                        </tr>
                      </thead>
                      <tbody className="bg-white divide-y divide-gray-200">
                        {ledger.map((entry) => (
                          <tr key={entry.id}>
                            <td className="px-3 py-2 whitespace-nowrap">
                              <span className={`px-2 inline-flex text-xs leading-5 font-semibold rounded-full ${
                                entry.entry_type === 'credit' ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'
                              }`}>
                                {entry.entry_type}
                              </span>
                            </td>
                            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900">
                              ₹{formatPaise(entry.amount_paise)}
                            </td>
                            <td className="px-3 py-2 whitespace-nowrap">
                              <span className={`px-2 inline-flex text-xs leading-5 font-semibold rounded-full ${getStatusColor(entry.status)}`}>
                                {entry.status}
                              </span>
                            </td>
                            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-500">
                              {entry.reference || '-'}
                            </td>
                            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-500">
                              {new Date(entry.created_at).toLocaleDateString()}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </div>
          </>
        )}
      </main>
    </div>
  )
}

export default App