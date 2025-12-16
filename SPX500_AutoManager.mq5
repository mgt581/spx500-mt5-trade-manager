//+------------------------------------------------------------------+
//| SPX500 Auto Trade Manager (Manual Entry)                          |
//| Risk-managed auto SL / TP / BE / Trailing                         |
//| Version: 1.0                                                      |
//+------------------------------------------------------------------+

#property strict

// ===== USER INPUTS (Plain English) =====
input double RiskPercent      = 0.5;   // Risk per trade (% of balance)
input double StopLossPoints   = 15;    // Stop loss in SPX points
input double TakeProfitPoints = 30;    // Take profit in SPX points
input double BreakEvenPoints  = 10;    // Move SL to BE after this profit
input double TrailPoints      = 10;    // Trailing stop distance after BE
input ulong  MagicNumber      = 50001; // Identifier for this EA

// ===== INTERNAL =====
bool breakevenDone = false;

//+------------------------------------------------------------------+
int OnInit()
{
   Print("SPX500 Auto Manager loaded.");
   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
void OnTick()
{
   if(PositionSelect(_Symbol))
   {
      ulong ticket = PositionGetInteger(POSITION_TICKET);
      if(PositionGetInteger(POSITION_MAGIC) != MagicNumber) return;

      ManageTrade();
   }
}

//+------------------------------------------------------------------+
void ManageTrade()
{
   double entryPrice = PositionGetDouble(POSITION_PRICE_OPEN);
   double sl         = PositionGetDouble(POSITION_SL);
   double tp         = PositionGetDouble(POSITION_TP);
   double price      = SymbolInfoDouble(_Symbol, SYMBOL_BID);

   ENUM_POSITION_TYPE type = (ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE);

   double profitPoints;
   if(type == POSITION_TYPE_BUY)
      profitPoints = (price - entryPrice);
   else
      profitPoints = (entryPrice - price);

   // ===== BREAK EVEN =====
   if(!breakevenDone && profitPoints >= BreakEvenPoints)
   {
      ModifySL(entryPrice);
      breakevenDone = true;
      Print("Break-even activated.");
   }

   // ===== TRAILING STOP =====
   if(breakevenDone)
   {
      double newSL;
      if(type == POSITION_TYPE_BUY)
         newSL = price - TrailPoints;
      else
         newSL = price + TrailPoints;

      if((type == POSITION_TYPE_BUY && newSL > sl) ||
         (type == POSITION_TYPE_SELL && newSL < sl))
      {
         ModifySL(newSL);
      }
   }
}

//+------------------------------------------------------------------+
void ModifySL(double newSL)
{
   MqlTradeRequest request;
   MqlTradeResult  result;
   ZeroMemory(request);

   request.action   = TRADE_ACTION_SLTP;
   request.symbol   = _Symbol;
   request.sl       = newSL;
   request.tp       = PositionGetDouble(POSITION_TP);
   request.position = PositionGetInteger(POSITION_TICKET);

   OrderSend(request, result);
}

//+------------------------------------------------------------------+
double CalculateLotSize()
{
   double balance   = AccountInfoDouble(ACCOUNT_BALANCE);
   double riskMoney = balance * (RiskPercent / 100.0);
   double tickValue = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);

   return NormalizeDouble(riskMoney / (StopLossPoints * tickValue), 2);
}

//+------------------------------------------------------------------+
void OnTradeTransaction(const MqlTradeTransaction& trans,
                        const MqlTradeRequest& request,
                        const MqlTradeResult& result)
{
   if(trans.type == TRADE_TRANSACTION_POSITION_OPEN)
   {
      double lotSize = CalculateLotSize();
      double price   = trans.price;

      double sl, tp;

      if(trans.position_type == POSITION_TYPE_BUY)
      {
         sl = price - StopLossPoints;
         tp = price + TakeProfitPoints;
      }
      else
      {
         sl = price + StopLossPoints;
         tp = price - TakeProfitPoints;
      }

      MqlTradeRequest mod;
      MqlTradeResult  res;
      ZeroMemory(mod);

      mod.action   = TRADE_ACTION_SLTP;
      mod.symbol   = _Symbol;
      mod.sl       = sl;
      mod.tp       = tp;
      mod.position = trans.position;

      OrderSend(mod, res);
   }
}
//+------------------------------------------------------------------+
